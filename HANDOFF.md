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
- **Known issues:** Backfill loaded <FILES> files and <ITEMS> items; table holds 1,685 rows. Athena check query returns 81 series. Dropbox US Basic is a new series with no history. Test events are Private, so each person creates their own. Athena statements 4-5 are left for Part 3.
- **Done when:** [x] table holds all history + a new daily row arrived on its own; an Athena query returns rows.

## Part 3 — Detection & output — owner: <your name>

- **Status:** [x] done — date: 2026-10-21

| Resource | Name | Notes |
| --- | --- | --- |
| Table | `pdd-alerts` | partition `series`, sort `alert_id` (`{date}#{alert_type}`), on-demand |
| Lambdas | `pdd-detector`, `pdd-alerter`, `pdd-dashboard` | Python 3.12, role `pdd-lambda-role`; detector invokes alerter when it finds new alerts |
| Schedule | `pdd-daily-detect` | `cron(15 6 * * ? *)` = 11:45 IST (after scrape 11:30, before export 12:00) |
| Topic | `pdd-alerts` | `arn:aws:sns:ap-south-1:778799435243:pdd-alerts`, email subscriptions must be confirmed |
| Athena | `pdd_db.alerts`, view `pdd_db.prices_with_alerts` | alerts table reads `s3://pdd-snigdha-data/exports/alerts/` |
| Dashboard | `pdd-dashboard` (Lambda Function URL, auth NONE) | URL: `<paste Function URL>`; reads DynamoDB live on every page load |

- **Code:** `aws/part3/` (`detector/`, `alerter/`, `dashboard/`); Athena DDL in `aws/part2/athena.sql` statements 4–5.
- **Detection rules:** `out_of_band` = price changed and is outside mean ± 2σ of the previous 6 observations (min 3); `stealth_hike` = price up with features unchanged, or price up while storage shrank; `shrinkflation` = storage down, price same or higher. Rows flagged `suspect` are ignored.
- **Backtest:** `<N>` alerts over the full history (`out_of_band` <N>, `stealth_hike` <N>, `shrinkflation` <N>), all stored with `mode = backtest`, `notified = true` so none were emailed. Notable: Apple Music price rise in IN and US (Aug 2026); Spotify IN Standard/Student cut ~30% (Jun 2026).
- **How to test:** In `pdd-prices`, duplicate the newest `icloud#IN#iCloud+ 50 GB` row, set `date` to tomorrow and `price_value` to 99. Run `pdd-detector` with `{}` → expect `new_alerts: 2` (out_of_band + stealth_hike) and an email "Price Drift Detector: 2 new alert(s)". Refresh the dashboard → alert at the top. Rerun → `new_alerts: 0`, no email. Then delete the fake price row and its two alerts.
- **Known issues:**
  - Quick Sight could not be used: not available on the AWS Free plan (and ~$290/month after its trial). Replaced by the `pdd-dashboard` Lambda, which is free and live.
  - The dashboard link is public (anyone with the URL can view). Acceptable: it only shows public subscription prices. The chart library loads from jsDelivr, so the viewer needs internet.
  - Wayback history has no feature text, so any older price rise also counts as a `stealth_hike`.
  - If a backtest is run after a fake row is added, it records the fake alerts as already notified and no email is sent; delete those alerts and rerun the daily event.
  - Dropbox US Basic is a new series with no history, so it can't trigger `out_of_band` until it has 3 observations.
  - Test events are Private; each person creates their own (`backtest` = `{"mode": "backtest"}`, `daily` = `{}`, alerter `run` = `{}`).
- **Done when:** [x] a fake price-hike row triggers an alert email and shows on the dashboard.
