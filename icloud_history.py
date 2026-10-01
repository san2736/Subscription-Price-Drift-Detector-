"""
iCloud+ price history (India + US) from documented sources, saved as monthly
snapshots in the same format as scraper.py / backfill.py.

iCloud+ prices in India and the US did not change during 2023-2026:
  - India 50GB/200GB/2TB = Rs 75 / Rs 219 / Rs 749 (unchanged since GST revision, Aug 2017)
  - US    50GB/200GB/2TB = $0.99 / $2.99 / $9.99
  - Apple's June 2023 iCloud+ price rise hit UK, Brazil, etc. but NOT India or the US.
6TB and 12TB tiers launched with iOS 17 (Sept 2023); their prices are taken from
today's live scrape (data/icloud/{region}/ latest file) and applied from Oct 2023.

Usage:  python3 icloud_history.py          (writes 2023-01 .. last month)
"""
import glob, json, os
from datetime import date

SOURCES = [
    "https://www.digit.in/news/mobile-phones/apples-icloud-storage-plans-will-cost-you-18-more-thanks-to-gst-36096.html",
    "https://www.gsmarena.com/apple_raises_icloud_pricing_in_the_uk_parts_of_europe_asia_and_the_americas-news-58989.php",
]
BASE = {
    "IN": {"currency": "INR", "prices": {"50 GB": "Rs 75", "200 GB": "Rs 219", "2 TB": "Rs 749"}},
    "US": {"currency": "USD", "prices": {"50 GB": "$0.99", "200 GB": "$2.99", "2 TB": "$9.99"}},
}
BIG_TIERS_FROM = (2023, 10)       # 6TB / 12TB available from here on


def latest_live(region):
    """Prices for 6 TB / 12 TB from the newest live scrape."""
    files = sorted(glob.glob(f"data/icloud/{region}/*.json"))
    for path in reversed(files):
        data = json.load(open(path, encoding="utf-8"))
        if data.get("source") != "documented":
            return {p["features"]: p["price_raw"] for p in data["plans"]}
    return {}


def price_value(text):
    return float("".join(c for c in text if c.isdigit() or c == "."))


def months(start=(2023, 1)):
    y, m = start
    today = date.today()
    while (y, m) < (today.year, today.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


for region, info in BASE.items():
    live = latest_live(region)
    folder = f"data/icloud/{region}"
    os.makedirs(folder, exist_ok=True)
    written = 0
    for y, m in months():
        path = f"{folder}/{y}-{m:02d}-01.json"
        if os.path.exists(path):
            continue
        prices = dict(info["prices"])
        if (y, m) >= BIG_TIERS_FROM:
            for tier in ["6 TB", "12 TB"]:
                if tier in live:
                    prices[tier] = live[tier]
        plans = []
        for tier, raw in prices.items():
            n = float(tier.split()[0])
            plans.append({
                "plan_name": f"iCloud+ {tier}", "features": tier,
                "storage_gb": n * 1000 if "TB" in tier else n,
                "price_raw": raw, "price_value": price_value(raw),
                "currency": info["currency"],
            })
        snapshot = {
            "service": "icloud", "region": region, "currency": info["currency"],
            "scraped_at": f"{y}-{m:02d}-01T00:00:00+00:00",
            "url": "https://support.apple.com/en-in/108047",
            "source": "documented", "sources": SOURCES, "plans": plans,
        }
        json.dump(snapshot, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        written += 1
    print(f"✓ icloud {region}: {written} monthly snapshots written to {folder}/")
