"""Convert all historical price data in the repo into the S3 raw-snapshot layout.

Usage (from the repo root):
    python aws/setup/normalize_history.py

Reads:
    data/{service}/{region}/{YYYY-MM-DD}.json   already in the right shape -> copied unchanged
    prices_all.csv                              Google One + Microsoft 365 (flat rows)
    data/spotify_yt_jiohotstar_zee5.csv         Spotify, YouTube, JioHotstar, ZEE5 (flat rows)

Writes:
    build/raw/{service}/{region}/{YYYY-MM-DD}.json   one snapshot per service, region, day
    build/manifest.csv                               one line per file, for checking the upload

Every output file follows aws/CONTRACTS.md (section 2). Upload build/raw to s3://<bucket>/raw/.
"""
import csv
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "build"
RAW_OUT = OUT / "raw"

CURRENCY_BY_SYMBOL = {"$": ("US", "USD"), "€": ("EU", "EUR"), "₹": ("IN", "INR"), "Rs": ("IN", "INR")}
CURRENCY_BY_REGION = {"US": "USD", "IN": "INR", "EU": "EUR"}
SERVICE_SLUG = {"Spotify": "spotify", "YouTube": "youtube", "JioHotstar": "jiohotstar", "ZEE5": "zee5"}


def parse_price(text):
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(match.group().replace(",", "")) if match else None


def storage_gb(plan_name):
    match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)\b", plan_name, re.I)
    if not match:
        return None
    size = float(match.group(1))
    return size * 1000 if match.group(2).upper() == "TB" else size


def snapshot(service, region, date, url, source, plans, extra=None):
    record = {
        "service": service,
        "region": region,
        "currency": CURRENCY_BY_REGION.get(region, plans[0].get("currency")),
        "scraped_at": f"{date}T00:00:00+00:00",
        "url": url,
        "source": source,
        "plans": plans,
    }
    if extra:
        record.update(extra)
    return record


def write(record, written):
    path = RAW_OUT / record["service"] / record["region"] / f"{record['scraped_at'][:10]}.json"
    if path.exists():
        sys.exit(f"collision: {path} would be written twice; check the inputs")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append((record, path))


def copy_existing_snapshots(written):
    """data/{service}/{region}/{date}.json files are already in the contract shape."""
    for src in sorted((ROOT / "data").glob("*/*/*.json")):
        record = json.loads(src.read_text(encoding="utf-8"))
        service, region, date = src.parts[-3], src.parts[-2], src.stem
        if record.get("service") != service or record.get("region") != region:
            sys.exit(f"{src}: service/region inside the file don't match its folder")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            sys.exit(f"{src}: file name is not YYYY-MM-DD")
        dest = RAW_OUT / service / region / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        written.append((record, dest))


def convert_prices_all(written):
    """Google One + Microsoft 365, scraped from the Wayback Machine as flat rows.

    Region comes from the currency on the archived page: the Wayback crawler sometimes saw
    the EU page, so EUR rows become their own EU series instead of polluting the US one.
    Microsoft 365 rows use the locale in the page URL (en-us / en-in).
    """
    groups = defaultdict(dict)  # (service, region, date) -> {plan: row}
    duplicates = 0
    for row in csv.DictReader(open(ROOT / "prices_all.csv", encoding="utf-8")):
        locale = re.search(r"\.com/([a-z]{2})-([a-z]{2})/", row["source_page"])
        if locale:
            region = locale.group(2).upper()
        else:
            symbol = re.match(r"\D*", row["price_raw"]).group().strip()
            region = CURRENCY_BY_SYMBOL[symbol][0]
        key = (row["service"], region, row["snapshot_date"])
        if row["plan"] in groups[key]:
            duplicates += 1  # same plan archived from /about and /about/plans on the same day
            continue
        groups[key][row["plan"]] = row

    for (service, region, date), plans_by_name in sorted(groups.items()):
        rows = list(plans_by_name.values())
        plans = []
        for row in rows:
            plan = {
                "plan_name": row["plan"],
                "features": row["plan"],
                "price_raw": row["price_raw"],
                "price_value": float(row["price_num"]) if row["price_num"] else parse_price(row["price_raw"]),
                "currency": CURRENCY_BY_REGION[region],
            }
            gb = storage_gb(row["plan"])
            if gb:
                plan["storage_gb"] = gb
            plans.append(plan)
        write(snapshot(service, region, date, rows[0]["source_page"], "wayback", plans,
                       {"archive_url": rows[0]["snapshot_url"]}), written)
    return duplicates


def convert_streaming_csv(written):
    """Spotify, YouTube, JioHotstar, ZEE5 — one row per plan, billing period and date."""
    groups = defaultdict(list)
    for row in csv.DictReader(open(ROOT / "data" / "spotify_yt_jiohotstar_zee5.csv", encoding="utf-8")):
        groups[(SERVICE_SLUG[row["service"]], row["region"], row["date"], row["source"])].append(row)

    by_day = defaultdict(list)
    for (service, region, date, source), rows in groups.items():
        by_day[(service, region, date)].append((source, rows))

    for (service, region, date), sources in sorted(by_day.items()):
        plans, used_sources = [], sorted({s for s, _ in sources})
        for _, rows in sources:
            for row in rows:
                tier = row["series"].split(" | ")[1]
                plan = {
                    "plan_name": tier if row["billing"] == "monthly" else f"{tier} ({row['billing']})",
                    "features": "",
                    "billing": row["billing"],
                    "price_raw": f"₹{row['price']}",
                    "price_value": float(row["price"]),
                    "currency": "INR",
                }
                if row["list_price"]:
                    plan["list_price"] = float(row["list_price"])
                if row["flag"]:
                    plan["flag"] = row["flag"]
                plans.append(plan)
        write(snapshot(service, region, date, "", "+".join(used_sources), plans), written)


def main():
    if not (ROOT / "data").is_dir() or not (ROOT / "prices_all.csv").is_file():
        sys.exit("run this from the repo root (the folder that has data/ and prices_all.csv)")
    if OUT.exists():
        shutil.rmtree(OUT)
    RAW_OUT.mkdir(parents=True)

    written = []
    copy_existing_snapshots(written)
    duplicates = convert_prices_all(written)
    convert_streaming_csv(written)

    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        out = csv.writer(f)
        out.writerow(["s3_key", "service", "region", "date", "source", "plans"])
        for record, path in written:
            key = "raw/" + path.relative_to(RAW_OUT).as_posix()
            out.writerow([key, record["service"], record["region"], path.stem,
                          record.get("source", "live"), len(record["plans"])])

    summary = Counter((r["service"], r["region"]) for r, _ in written)
    dates = defaultdict(list)
    for r, p in written:
        dates[(r["service"], r["region"])].append(p.stem)
    print(f"{'service':<14}{'region':<8}{'files':>6}  first       last")
    for (service, region), n in sorted(summary.items()):
        d = sorted(dates[(service, region)])
        print(f"{service:<14}{region:<8}{n:>6}  {d[0]}  {d[-1]}")
    print(f"\n{len(written)} files in {RAW_OUT}  ({duplicates} duplicate Wayback rows dropped)")
    print(f"manifest: {OUT / 'manifest.csv'}")


if __name__ == "__main__":
    main()
