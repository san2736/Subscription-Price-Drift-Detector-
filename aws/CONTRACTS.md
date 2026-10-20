# Data contracts — Subscription Price Drift Detector (AWS)

Every part reads what the previous part wrote. These shapes and names are the agreement
between parts. **If you change one, update this file in the same commit and say so in
`HANDOFF.md`.**

## 1. Conventions

| Item | Value |
| --- | --- |
| Region | `ap-south-1` (Mumbai) for everything |
| Name prefix | `pdd-` on every resource (Glue/Athena: `pdd_`, hyphens aren't allowed there) |
| Bucket | `pdd-snigdha-data` (change here if the real name differs) |
| Lambda runtime | Python 3.12, x86_64, for every function and the layer |
| Lambda role | `pdd-lambda-role` (choose **Use an existing role**; teammates cannot create roles) |
| Times | UTC everywhere. Dates are `YYYY-MM-DD`, timestamps ISO 8601 with `+00:00` |
| Code | Every Lambda's code lives in `aws/part1/`, `aws/part2/` or `aws/part3/`; never only in the console |

## 2. Raw snapshot (S3) — written by setup (history) and Part 1 (daily)

Key: `raw/{service}/{region}/{YYYY-MM-DD}.json`

- `service`: lowercase slug — `netflix`, `icloud`, `apple_music`, `dropbox`, `googleone`,
  `microsoft365`, `spotify`, `youtube`, `jiohotstar`, `zee5`
- `region`: `IN`, `US` or `EU`
- One file per service, region and day. A rerun on the same day overwrites (versioning keeps the old one).
- A failed scrape never writes under `raw/`. Part 1 writes `errors/{service}/{region}/{YYYY-MM-DD}.json`
  instead (`service`, `region`, `config_key`, `url`, `error`, `scraped_at`), so `raw/` only ever holds good snapshots.

```json
{
  "service": "netflix",
  "region": "IN",
  "currency": "INR",
  "scraped_at": "2026-10-01T16:25:17.653626+00:00",
  "url": "https://help.netflix.com/en/node/24926?q=netflix%20plans",
  "source": "live",
  "plans": [
    {
      "plan_name": "Standard",
      "features": "Watch on 2 supported devices | 1080p (Full HD) | ...",
      "price_raw": "₹499",
      "price_value": 499.0,
      "currency": "INR"
    }
  ]
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `service`, `region`, `currency`, `scraped_at`, `plans` | yes | |
| `url` | yes | may be `""` for news-report history |
| `source` | no | `live` if missing; history uses `wayback`, `documented`, `news_reports` (or `a+b`) |
| `archive_url` | no | Wayback snapshot used |
| `plans[].plan_name` | yes | non-monthly billing is in the name, e.g. `Premium HD (annual)` |
| `plans[].price_value` | yes | float, in `currency`. `null` = scrape found the plan but no price; Part 2 skips the plan |
| `plans[].price_raw`, `plans[].currency` | yes | |
| `plans[].features` | yes | `" \| "`-joined text; may be `""` |
| `plans[].storage_gb` | no | storage services |
| `plans[].billing`, `plans[].list_price`, `plans[].flag` | no | from the streaming history CSV; `flag: "suspect"` = doubtful data point |

## 3. Scraper config (S3) — owned by Part 1

Key: `config/services_config.json` — same shape as the repo's `services_config.json`
(one entry per service+region, with `service`, `url`, `region`, `currency`, `method` and
method-specific fields).

## 4. Prices table (DynamoDB) — created by Part 2

Table: `pdd-prices`, capacity mode **On-demand**.

| Attribute | Type | Key | Example |
| --- | --- | --- | --- |
| `series` | S | partition | `netflix#IN#Standard` |
| `date` | S | sort | `2026-10-01` |
| `service`, `region`, `plan_name`, `currency` | S | | |
| `price_value` | N | | `499` |
| `price_raw`, `features`, `source`, `s3_key`, `scraped_at` | S | | |
| `features_hash` | S | | first 16 hex chars of SHA-256 of `features` lower-cased with whitespace collapsed |
| `storage_gb`, `list_price` | N | | only when present |
| `billing`, `flag` | S | | only when present |

One item per plan per snapshot. Writing the same `series` + `date` again overwrites (idempotent),
so the backfill can be rerun safely. Plans with `price_value: null` are skipped (logged).

## 5. Exports for Athena / QuickSight — written by Part 2

- `exports/prices/prices.jsonl` and `exports/alerts/alerts.jsonl` — JSON Lines, one object per
  line, same attributes as the tables. Rewritten whole by `pdd-export` daily at 06:30 UTC.
- Athena: database `pdd_db`, tables `pdd_db.prices` and `pdd_db.alerts`, view
  `pdd_db.prices_with_alerts`, workgroup `pdd-workgroup`, query results in
  `s3://pdd-snigdha-data/athena-results/`. DDL in `aws/part2/athena.sql`.

## 6. Alerts table (DynamoDB) — created by Part 3

Table: `pdd-alerts`, On-demand.

| Attribute | Type | Key | Notes |
| --- | --- | --- | --- |
| `series` | S | partition | same as `pdd-prices` |
| `alert_id` | S | sort | `{date}#{alert_type}` — rerunning detection never duplicates an alert |
| `date`, `alert_type` | S | | `out_of_band`, `stealth_hike` or `shrinkflation` |
| `service`, `region`, `plan_name`, `currency`, `previous_date` | S | | |
| `price_value`, `previous_price`, `change_pct` | N | | |
| `expected_mean`, `expected_std` | N | | `out_of_band` only |
| `storage_before`, `storage_after` | N | | when the plan has `storage_gb` |
| `rule` | S | | the rule that fired, in words |
| `features_before`, `features_after` | S | | `stealth_hike` only |
| `mode` | S | | `daily` or `backtest` |
| `notified` | BOOL | | `false` until the alerter emails it; backtest alerts are stored `true` (never emailed) |
| `detected_at` | S | | ISO timestamp |

## 7. Resource names

| Resource | Name | Part |
| --- | --- | --- |
| Lambda layer | `pdd-scraping-deps` | 1 |
| Scraper / dispatcher Lambdas | `pdd-scraper`, `pdd-dispatcher` | 1 |
| Daily schedule | EventBridge rule `pdd-daily-scrape`, `cron(0 6 * * ? *)` = 11:30 IST | 1 |
| Playwright image (only if needed) | ECR repo `pdd-scraper-browser` | 1 |
| Parser Lambda (S3 trigger on `raw/`; backfill = test event `{"backfill": true}`) | `pdd-parser` | 2 |
| Export Lambda + schedule | `pdd-export`, rule `pdd-daily-export`, `cron(30 6 * * ? *)` = 12:00 IST | 2 |
| Detector Lambda + schedule | `pdd-detector`, rule `pdd-daily-detect`, `cron(15 6 * * ? *)` = 11:45 IST | 3 |
| Alerter Lambda (invoked by the detector) | `pdd-alerter` | 3 |
| SNS topic | `pdd-alerts` | 3 |
| Dashboard | Amazon Quick Sight, dashboard `Price Drift Detector` | 3 |
| State machine (stretch) | `pdd-pipeline`, role `pdd-sfn-role` | any |
