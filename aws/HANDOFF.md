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

## Part 1 — Ingestion — owner: Alisha

- **Status:** [x] done — date: 2026-10-20

| Resource | Name | Notes |
| --- | --- | --- |
| Layer | `pdd-scraping-deps` | Version 1, ARN: `arn:aws:lambda:ap-south-1:778799435243:layer:pdd-scraping-deps:1` |
| Lambdas | `pdd-dispatcher`, `pdd-scraper` | Python 3.12, role `pdd-lambda-role` |
| Schedule | `pdd-daily-scrape` | `cron(0 6 * * ? *)` = 11:30 IST |

- **Code:** `aws/part1/`
- **How to test:** Run the `all` test event on `pdd-dispatcher`, then check today's files under `raw/`.
- **Services that fail / are excluded and why:** None failing. Only the six live services are scraped (netflix IN, icloud IN/US, apple_music IN/US, dropbox US). The other six are history only; Task 7 (adding them live) was skipped.
- **Known issues:** `dropbox_US` now returns 4 plans (Basic, Plus, Standard, Advanced). Basic is new since 1 Oct, so Part 2 will see it as a new series with no history. No 403 blocks so far.
- **Done when:** [x] two scheduled runs in a row (10-minute test rate) wrote files for every service; CloudWatch shows no errors; rule is back on `cron(0 6 * * ? *)`.

---

## Part 2 — Storage — owner:

- **Status:** [ ] done — date:

| Resource | Name | Notes |
| --- | --- | --- |
| Table | `pdd-prices` | |
| Lambdas | `pdd-parser`, `pdd-export` | |
| Schedule | `pdd-daily-export` | |
| Athena | `pdd_db.prices`, workgroup `pdd-workgroup` | |

- **Code:** `aws/part2/`
- **How to test:**
- **Known issues:**
- **Done when:** [ ] table holds all history + a new daily row arrived on its own; an Athena query returns rows.

---

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
