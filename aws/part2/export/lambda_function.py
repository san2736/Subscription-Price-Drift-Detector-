"""pdd-export — copies DynamoDB tables to S3 as JSON Lines, for Athena and QuickSight.

QuickSight can't read DynamoDB directly, so this writes one file per table, replacing the
previous export each run. Runs daily (EventBridge rule pdd-daily-export) and on demand.

Environment variables:
    BUCKET   pdd-yourname-data
    EXPORTS  pdd-prices=exports/prices/prices.jsonl,pdd-alerts=exports/alerts/alerts.jsonl
             (a table that doesn't exist yet is skipped, so Part 2 can deploy this before
             Part 3 creates pdd-alerts)
"""
import json
import os
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]


def plain(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def scan_all(table):
    kwargs = {}
    while True:
        page = table.scan(**kwargs)
        yield from page["Items"]
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def lambda_handler(event, context):
    results = {}
    for pair in os.environ["EXPORTS"].split(","):
        table_name, key = (p.strip() for p in pair.split("="))
        table = dynamodb.Table(table_name)
        try:
            rows = [json.dumps({k: plain(v) for k, v in item.items()}, ensure_ascii=False)
                    for item in scan_all(table)]
        except dynamodb.meta.client.exceptions.ResourceNotFoundException:
            results[table_name] = "table not found, skipped"
            continue
        s3.put_object(Bucket=BUCKET, Key=key, Body=("\n".join(rows) + "\n").encode("utf-8"),
                      ContentType="application/x-ndjson")
        results[table_name] = f"{len(rows)} rows -> s3://{BUCKET}/{key}"
    print(json.dumps(results))
    return results
