"""pdd-dispatcher — reads the scraper config from S3 and starts one pdd-scraper per entry.

Triggered daily by the EventBridge rule pdd-daily-scrape. Each scraper runs asynchronously,
so one slow or broken site can't stop the others.

Test event for the console:
    {}                              # dispatch every entry
    {"only": ["netflix"]}           # dispatch just these config keys

A config entry may name a different function with "function": "pdd-scraper-browser"
(the Playwright container for JavaScript-rendered pages); everything else goes to
SCRAPER_FUNCTION.

Environment variables:
    BUCKET            pdd-yourname-data
    CONFIG_KEY        config/services_config.json
    SCRAPER_FUNCTION  pdd-scraper
"""
import json
import os

import boto3

s3 = boto3.client("s3")
lam = boto3.client("lambda")
BUCKET = os.environ["BUCKET"]
CONFIG_KEY = os.environ.get("CONFIG_KEY", "config/services_config.json")
SCRAPER_FUNCTION = os.environ.get("SCRAPER_FUNCTION", "pdd-scraper")


def lambda_handler(event, context):
    configs = json.loads(s3.get_object(Bucket=BUCKET, Key=CONFIG_KEY)["Body"].read())
    only = set((event or {}).get("only") or [])
    unknown = only - configs.keys()
    if unknown:
        raise KeyError(f"not in config: {sorted(unknown)}")

    dispatched = []
    for key, config in configs.items():
        if only and key not in only:
            continue
        lam.invoke(
            FunctionName=config.get("function", SCRAPER_FUNCTION),
            InvocationType="Event",  # async: fire and forget
            Payload=json.dumps({"key": key, "config": config}).encode("utf-8"),
        )
        dispatched.append(key)

    print(json.dumps({"dispatched": dispatched}))
    return {"dispatched": dispatched, "count": len(dispatched)}
