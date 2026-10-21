# Handoff log

Each part adds its section **before** passing on. The next person starts only when the
previous section's "Done when" box is ticked. Names and shapes are in `CONTRACTS.md`.

---
## Setup — account owner

- **Status:** [x] done — date: 2026-10-20
- **Sign-in URL:** `https://pdd-snigdha.signin.aws.amazon.com/console`
- **Region:** ap-south-1 (Mumbai)

| Resource | Name / ARN |
| --- | --- |
| S3 bucket | `pdd-snigdha-data` |
| Lambda execution role | `arn:aws:iam::778799435243:role/pdd-lambda-role` |
| Step Functions role | `arn:aws:iam::778799435243:role/pdd-sfn-role` |
| Team group / policy | `pdd-team` / `pdd-team-policy` |
| Budgets | `pdd-zero-spend`, `pdd-monthly` ($5) |

- **History uploaded:** 425 files under `raw/` (from `python aws/setup/normalize_history.py`)
- **Config uploaded:** `config/services_config.json`
- **How to check:** S3 → bucket → `raw/` shows one folder per service; file count matches the line above.
- **Known issues / notes:** Team policy was first created with the placeholder account ID and had to be replaced with the filled version. Teammates: Lambda creation should now work; tell the account owner if you see `lambda:CreateFunction` errors. Three teammate users (not two), so all four emails are on the budgets.
- **Done when:** [ ] all three teammates have signed in, set MFA and opened the bucket.
---

## Part 1 — Ingestion — owner:

- **Status:** [ ] done — date:

| Resource | Name | Notes |
| --- | --- | --- |
| Layer | `pdd-scraping-deps` | |
| Lambdas | `pdd-dispatcher`, `pdd-scraper` | |
| Schedule | `pdd-daily-scrape` | |

- **Code:** `aws/part1/`
- **How to test:** 
- **Services that fail / are excluded and why:**
- **Known issues:**
- **Done when:** [ ] two scheduled runs in a row (10-minute test rate) wrote files for every service; CloudWatch shows no errors; rule is back on `cron(0 6 * * ? *)`.

---

## Part 2 — Storage — owner: Snigdha

- **Status:** [x] done — date: 2026-10-21

| Resource | Name | Notes |
| --- | --- | --- |
| Table | `pdd-prices` | partition `series`, sort `date`, on-demand |
| Lambdas | `pdd-parser`, `pdd-export` | parser has S3 trigger on `raw/` + `.json` |
| Schedule | `pdd-daily-export` | `cron(30 6 * * ? *)` = 12:00 IST |
| Athena | `pdd_db.prices`, workgroup `pdd-workgroup` | results in `s3://pdd-snigdha-data/athena-results/` |

- **Code:** `aws/part2/`
- **How to test:** run `only-netflix` ({"only": ["netflix"]}) on `pdd-dispatcher`, then check the `pdd-parser` log for `items_written` above 0.
- **Known issues:** Backfill loaded <FILES> files and <ITEMS> items. Dropbox US Basic is a new series with no history. `pdd-alerts` doesn't exist until Part 3, so export skips it for now. Test events are Private, so each person creates their own.
- **Done when:** [x] table holds all history + a new daily row arrived on its own; an Athena query returns rows.

## Part 3 — Detection & output — owner:

- **Status:** [ ] done — date:

| Resource | Name | Notes |
| --- | --- | --- |
| Table | `pdd-alerts` | |
| Lambdas | `pdd-detector`, `pdd-alerter` | |
| Schedule | `pdd-daily-detect` | |
| Topic | `pdd-alerts` | |
| Athena | `pdd_db.alerts`, view `pdd_db.prices_with_alerts` | |
| Dashboard | Quick Sight `Price Drift Detector` | trial ends: |

- **Code:** `aws/part3/`
- **How to test:**
- **Known issues:**
- **Done when:** [ ] a fake price-hike row triggers an alert email and shows on the dashboard.
