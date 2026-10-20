"""pdd-scraper — scrapes ONE service+region and writes the snapshot to S3.

Deployed as a zip with the repo's scraper.py next to this file (see build_zip.py), so the
strategy functions are the same code the team runs locally.

Event (from pdd-dispatcher, or a console test event):
    {"key": "icloud_IN", "config": {...one entry of services_config.json...}}
    {"key": "icloud_IN"}                      # config is read from S3 instead

Environment variables:
    BUCKET      pdd-yourname-data
    CONFIG_KEY  config/services_config.json

Writes:
    raw/{service}/{region}/{YYYY-MM-DD}.json     on success (CONTRACTS.md section 2)
    errors/{service}/{region}/{YYYY-MM-DD}.json  on failure, then re-raises so the
                                                 Lambda Errors metric counts it
"""
import json
import os
from datetime import datetime, timezone

import boto3

import scraper  # the repo's scraper.py, bundled in the zip

s3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]
CONFIG_KEY = os.environ.get("CONFIG_KEY", "config/services_config.json")


def load_config(key):
    body = s3.get_object(Bucket=BUCKET, Key=CONFIG_KEY)["Body"].read()
    configs = json.loads(body)
    if key not in configs:
        raise KeyError(f"'{key}' is not in s3://{BUCKET}/{CONFIG_KEY}")
    return configs[key]


def put_json(key, record):
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )


def lambda_handler(event, context):
    key = event["key"]
    config = event.get("config") or load_config(key)
    service = config.get("service", key)
    region = config["region"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        result = scraper.scrape_service(key, config)
        plans = result["plans"]
        if not plans:
            raise ValueError("scraper returned 0 plans")
        missing = [p["plan_name"] for p in plans if p.get("price_value") is None]
        result["source"] = "live"
    except Exception as exc:
        error_key = f"errors/{service}/{region}/{today}.json"
        put_json(error_key, {
            "service": service, "region": region, "config_key": key,
            "url": config.get("url"), "error": f"{type(exc).__name__}: {exc}",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })
        print(json.dumps({"status": "error", "key": key, "error_key": error_key, "error": str(exc)}))
        raise

    raw_key = f"raw/{result['service']}/{result['region']}/{result['scraped_at'][:10]}.json"
    put_json(raw_key, result)
    summary = {"status": "ok", "key": key, "s3_key": raw_key, "plans": len(plans),
               "plans_without_price": missing}
    print(json.dumps(summary, ensure_ascii=False))
    return summary
