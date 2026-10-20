"""pdd-detector — finds price anomalies and stealth hikes in pdd-prices, writes them to pdd-alerts.

Rules, per series (service#region#plan), comparing each observation with the ones before it:

  out_of_band    the price changed from the previous observation AND sits outside
                 mean ± 2 standard deviations of the previous WINDOW observations
                 (needs at least MIN_HISTORY of them; if they were all equal, any change counts)
  stealth_hike   the price went up while the features text is unchanged, or storage shrank
  shrinkflation  storage shrank while the price stayed the same or rose (fewer GB for the money)

Observations flagged "suspect" in the data are ignored.

Modes (test event):
  {}                    daily mode: checks observations from the last LOOKBACK_DAYS days,
                        new alerts get notified=false and the alerter is invoked
  {"mode": "backtest"}  checks every observation in history; alerts are stored with
                        notified=true so the alerter never emails them

Re-running is safe: an alert is only written if its (series, alert_id) doesn't exist yet.

Environment variables:
    PRICES_TABLE      pdd-prices
    ALERTS_TABLE      pdd-alerts
    ALERTER_FUNCTION  pdd-alerter   (leave empty to skip invoking it)
    WINDOW            6
    MIN_HISTORY       3
    LOOKBACK_DAYS     2
"""
import json
import os
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
prices = dynamodb.Table(os.environ.get("PRICES_TABLE", "pdd-prices"))
alerts = dynamodb.Table(os.environ.get("ALERTS_TABLE", "pdd-alerts"))
ALERTER = os.environ.get("ALERTER_FUNCTION", "")
WINDOW = int(os.environ.get("WINDOW", "6"))
MIN_HISTORY = int(os.environ.get("MIN_HISTORY", "3"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "2"))


def num(value):
    return float(value) if value is not None else None


def dec(value):
    return Decimal(str(round(value, 4))) if value is not None else None


def scan_all(table):
    kwargs = {}
    while True:
        page = table.scan(**kwargs)
        yield from page["Items"]
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def check(current, history):
    """Return a list of alert dicts for `current` given earlier observations `history`."""
    if not history:
        return []
    last = history[-1]
    price, last_price = num(current["price_value"]), num(last["price_value"])
    change_pct = (price - last_price) / last_price * 100 if last_price else None
    storage, last_storage = num(current.get("storage_gb")), num(last.get("storage_gb"))
    storage_down = storage is not None and last_storage is not None and storage < last_storage
    price_up = price > last_price * 1.001
    features_same = current.get("features_hash") == last.get("features_hash")

    base = {
        "series": current["series"], "date": current["date"],
        "service": current["service"], "region": current["region"],
        "plan_name": current["plan_name"], "currency": current.get("currency", ""),
        "price_value": price, "previous_price": last_price, "previous_date": last["date"],
        "change_pct": change_pct,
    }
    found = []

    window = [num(h["price_value"]) for h in history[-WINDOW:]]
    if len(window) >= MIN_HISTORY and price != last_price:
        mean, std = statistics.fmean(window), statistics.pstdev(window)
        if (std == 0 and price != mean) or (std > 0 and abs(price - mean) > 2 * std):
            found.append({**base, "alert_type": "out_of_band", "expected_mean": mean,
                          "expected_std": std,
                          "rule": f"price outside mean ± 2σ of previous {len(window)} observations"})

    if price_up and (features_same or storage_down):
        found.append({**base, "alert_type": "stealth_hike",
                      "rule": "price up, features unchanged" if features_same else "price up, storage down",
                      "features_before": last.get("features", ""), "features_after": current.get("features", ""),
                      "storage_before": last_storage, "storage_after": storage})
    elif storage_down and price >= last_price:
        found.append({**base, "alert_type": "shrinkflation", "rule": "storage down, price same or higher",
                      "storage_before": last_storage, "storage_after": storage})
    return found


def detect(items, mode, today):
    by_series = defaultdict(list)
    for item in items:
        if item.get("flag") != "suspect":
            by_series[item["series"]].append(item)
    cutoff = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    results = []
    for series_items in by_series.values():
        series_items.sort(key=lambda i: i["date"])
        for i, current in enumerate(series_items):
            if mode == "daily" and current["date"] < cutoff:
                continue
            results.extend(check(current, series_items[:i]))
    return results


def save(alert, mode):
    item = {k: (dec(v) if isinstance(v, float) else v) for k, v in alert.items() if v is not None}
    item.update({"alert_id": f"{alert['date']}#{alert['alert_type']}", "mode": mode,
                 "notified": mode == "backtest",
                 "detected_at": datetime.now(timezone.utc).isoformat()})
    try:
        alerts.put_item(Item=item, ConditionExpression="attribute_not_exists(alert_id)")
        return True
    except alerts.meta.client.exceptions.ConditionalCheckFailedException:
        return False  # already recorded on an earlier run


def lambda_handler(event, context):
    mode = "backtest" if (event or {}).get("mode") == "backtest" else "daily"
    today = datetime.now(timezone.utc).date()
    found = detect(list(scan_all(prices)), mode, today)
    new = [a for a in found if save(a, mode)]
    summary = {"mode": mode, "alerts_found": len(found), "new_alerts": len(new),
               "by_type": {t: sum(a["alert_type"] == t for a in new) for t in ("out_of_band", "stealth_hike", "shrinkflation")}}
    if mode == "daily" and new and ALERTER:
        boto3.client("lambda").invoke(FunctionName=ALERTER, InvocationType="Event", Payload=b"{}")
        summary["alerter_invoked"] = ALERTER
    print(json.dumps(summary))
    return summary
