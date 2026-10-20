-- Part 2 / Part 3 Athena setup. Run each statement separately in the Athena query editor
-- with workgroup pdd-workgroup selected. Replace pdd-yourname-data if your bucket differs.

-- 1. Database (Glue names use underscores, not hyphens)
CREATE DATABASE IF NOT EXISTS pdd_db;

-- 2. Prices table over the pdd-export output
CREATE EXTERNAL TABLE IF NOT EXISTS pdd_db.prices (
  series        string,
  `date`        string,
  service       string,
  region        string,
  plan_name     string,
  currency      string,
  price_value   double,
  price_raw     string,
  features      string,
  features_hash string,
  storage_gb    double,
  list_price    double,
  billing       string,
  flag          string,
  source        string,
  s3_key        string,
  scraped_at    string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://pdd-yourname-data/exports/prices/';

-- 3. Check: one row per series, with its date range
SELECT service, region, plan_name, count(*) AS observations,
       min("date") AS first_date, max("date") AS last_date
FROM pdd_db.prices
GROUP BY service, region, plan_name
ORDER BY service, region, plan_name;

-- 4. (Part 3) Alerts table over the same export Lambda's second file
CREATE EXTERNAL TABLE IF NOT EXISTS pdd_db.alerts (
  series          string,
  alert_id        string,
  `date`          string,
  alert_type      string,
  service         string,
  region          string,
  plan_name       string,
  currency        string,
  price_value     double,
  previous_price  double,
  previous_date   string,
  change_pct      double,
  expected_mean   double,
  expected_std    double,
  `rule`          string,
  features_before string,
  features_after  string,
  storage_before  double,
  storage_after   double,
  mode            string,
  notified        boolean,
  detected_at     string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://pdd-yourname-data/exports/alerts/';

-- 5. (Part 3) View QuickSight uses for the price chart: prices with any alert on that day
CREATE OR REPLACE VIEW pdd_db.prices_with_alerts AS
SELECT p.*,
       a.alert_type,
       a.change_pct AS alert_change_pct,
       CASE WHEN a.alert_type IS NULL THEN 0 ELSE 1 END AS is_alert
FROM pdd_db.prices p
LEFT JOIN (
  SELECT series, "date", array_join(array_agg(alert_type), ', ') AS alert_type, max(change_pct) AS change_pct
  FROM pdd_db.alerts GROUP BY series, "date"
) a ON p.series = a.series AND p."date" = a."date";
