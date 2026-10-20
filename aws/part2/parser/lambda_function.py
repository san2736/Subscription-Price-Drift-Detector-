"""pdd-parser — turns raw S3 snapshots into one DynamoDB item per plan per day.

Two ways in:
  1. S3 trigger (ObjectCreated on prefix raw/, suffix .json) — every new snapshot Part 1 writes.
  2. Backfill test event — reprocesses everything already in S3 (the history uploaded in setup):
         {"backfill": true}                      # all of raw/
         {"backfill": true, "prefix": "raw/icloud/"}

Writes are idempotent (same series + date overwrites), so a backfill can be rerun safely.

Environment variables:
    TABLE   pdd-prices
"""
import hashlib
import json
import os
import re
import urllib.parse
from decimal import Decimal

import boto3

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ.get("TABLE", "pdd-prices"))


def features_hash(text):
    normalised = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def to_decimal(value):
    return Decimal(str(value)) if value is not None else None


def items_from_snapshot(snapshot, s3_key):
    """One item per plan that has a price. Returns (items, skipped_plan_names)."""
    items, skipped = [], []
    date = snapshot["scraped_at"][:10]
    for plan in snapshot.get("plans", []):
        if plan.get("price_value") is None:
            skipped.append(plan.get("plan_name"))
            continue
        item = {
            "series": f"{snapshot['service']}#{snapshot['region']}#{plan['plan_name']}",
            "date": date,
            "service": snapshot["service"],
            "region": snapshot["region"],
            "plan_name": plan["plan_name"],
            "currency": plan.get("currency") or snapshot.get("currency", ""),
            "price_value": to_decimal(plan["price_value"]),
            "price_raw": plan.get("price_raw", ""),
            "features": plan.get("features", ""),
            "features_hash": features_hash(plan.get("features", "")),
            "source": snapshot.get("source", "live"),
            "s3_key": s3_key,
            "scraped_at": snapshot["scraped_at"],
        }
        for key in ("storage_gb", "list_price"):
            if plan.get(key) is not None:
                item[key] = to_decimal(plan[key])
        for key in ("billing", "flag"):
            if plan.get(key):
                item[key] = plan[key]
        items.append(item)
    return items, skipped


def process_key(bucket, key, batch):
    snapshot = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    if "plans" not in snapshot or "error" in snapshot:
        print(json.dumps({"skipped_file": key, "reason": "no plans / error record"}))
        return 0
    items, skipped = items_from_snapshot(snapshot, key)
    for item in items:
        batch.put_item(Item=item)
    if skipped:
        print(json.dumps({"file": key, "plans_without_price": skipped}, ensure_ascii=False))
    return len(items)


def lambda_handler(event, context):
    written, files = 0, 0
    with table.batch_writer(overwrite_by_pkeys=["series", "date"]) as batch:
        if event.get("backfill"):
            bucket = os.environ["BUCKET"]
            prefix = event.get("prefix", "raw/")
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    if obj["Key"].endswith(".json"):
                        written += process_key(bucket, obj["Key"], batch)
                        files += 1
        else:
            for record in event.get("Records", []):
                bucket = record["s3"]["bucket"]["name"]
                key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
                written += process_key(bucket, key, batch)
                files += 1
    summary = {"files": files, "items_written": written}
    print(json.dumps(summary))
    return summary
