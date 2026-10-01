"""
Backfill historical prices from the Wayback Machine (archive.org).

Runs the SAME strategy functions from scraper.py on archived copies of each
pricing page (one per month). If a strategy fails because the old page had a
different layout, a layout-agnostic text fallback is tried (iCloud, Apple Music).

Usage (from the project folder, venv active):
    python3 backfill.py                     # all services, from 2023
    python3 backfill.py icloud_IN 2022      # one service, from 2022

Output: data/{service}/{region}/{date}.json  (+ "source": "wayback")
A summary per service is printed at the end.
"""
import json, os, re, sys, time
import requests
from bs4 import BeautifulSoup
from scraper import STRATEGIES, save_result, parse_price

HEADERS = {'User-Agent': 'Mozilla/5.0 (student project; price history backfill)'}
PRICE_RE = r'(?:Rs\.?|₹|INR|US\$|\$)\s?\d[\d,]*(?:\.\d+)?'
SIZE_RE = r'(\d+)\s?(GB|TB)'


def page_lines(soup):
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    return [" ".join(l.split()) for l in soup.get_text("\n").split("\n") if l.strip()]


# ---------- Fallback 1: iCloud+ as plain text (lists, paragraphs, older tables) ----------
def icloud_text_fallback(soup, config):
    country = config['country']
    lines = page_lines(soup)
    # tier names in page order, e.g. ["50 GB", "200 GB", "2 TB"]
    header_tiers = []
    for l in lines:
        m = re.fullmatch(r'(?:iCloud\+?\s*)?' + SIZE_RE + r'(?:\s*storage)?', l, re.I)
        if m:
            t = f"{m.group(1)} {m.group(2).upper()}"
            if t not in header_tiers:
                header_tiers.append(t)

    for i, line in enumerate(lines):
        if not re.match(rf'^{re.escape(country)}(?![A-Za-z])', line):
            continue
        block = [line]
        for nxt in lines[i + 1:i + 25]:
            # stop at the next country row, e.g. "Indonesia (IDR)"
            if re.search(r'\([A-Z]{3}\)', nxt) and not re.match(rf'^{re.escape(country)}', nxt):
                break
            block.append(nxt)
        text = " ".join(block)

        plans = []
        # Case A: size and price written together, e.g. "50 GB: Rs 75"
        for size, unit, price in re.findall(SIZE_RE + r'\s*[:\-–]?\s*(' + PRICE_RE + ')', text, re.I):
            plans.append((f"{size} {unit.upper()}", price))
        # Case B: only prices, in the same order as the tier header
        if not plans and header_tiers:
            prices = re.findall(PRICE_RE, text)
            plans = list(zip(header_tiers, prices))
        if plans:
            out = []
            for tier, price in plans:
                n = parse_price(tier)
                out.append({
                    "plan_name": f"iCloud+ {tier}",
                    "features": tier,
                    "storage_gb": n * 1000 if "TB" in tier else n,
                    "price_raw": price.strip(),
                    "price_value": parse_price(price),
                    "currency": config['currency'],
                })
            return out

    # Old regional pages (en-in / en-us) may show ONLY that country's prices, with no country table:
    # read "50 GB ... Rs 75" pairs from the whole page.
    text = " ".join(lines)
    pairs = re.findall(SIZE_RE + r'[^0-9₹$]{0,40}?(' + PRICE_RE + ')', text, re.I)
    seen, out = set(), []
    for size, unit, price in pairs:
        tier = f"{size} {unit.upper()}"
        if tier in seen or (config['currency'] == "INR") != bool(re.search(r'Rs|₹|INR', price)):
            continue
        seen.add(tier)
        n = float(size)
        out.append({
            "plan_name": f"iCloud+ {tier}", "features": tier,
            "storage_gb": n * 1000 if unit.upper() == "TB" else n,
            "price_raw": price.strip(), "price_value": parse_price(price),
            "currency": config['currency'],
        })
    return out if len(out) >= 2 else []


# ---------- Fallback 2: Apple Music as plain text ("Individual ... ₹99/month") ----------
def apple_music_text_fallback(soup, config):
    text = " ".join(page_lines(soup))
    plans = []
    for name in ["Individual", "Family", "Student", "Voice"]:
        m = re.search(name + r'.{0,80}?(' + PRICE_RE + r')\s*(?:/|per)\s*mo', text)
        if m:
            plans.append({
                "plan_name": name, "features": "",
                "price_raw": m.group(1), "price_value": parse_price(m.group(1)),
                "currency": config['currency'],
            })
    return plans


FALLBACKS = {"icloud_table": icloud_text_fallback, "apple_music": apple_music_text_fallback}


def extract(soup_html, cfg):
    """Try the normal strategy first, then the fallback for old layouts."""
    errors = []
    try:
        plans = STRATEGIES[cfg['method']](BeautifulSoup(soup_html, 'html.parser'), cfg)
        if plans and any(p.get('price_value') for p in plans):
            return plans, "strategy"
    except Exception as e:
        errors.append(str(e))
    fb = FALLBACKS.get(cfg['method'])
    if fb:
        plans = fb(BeautifulSoup(soup_html, 'html.parser'), cfg)
        if plans:
            return plans, "fallback"
    raise ValueError("; ".join(errors) or "no plans found")


def polite_get(url, **kw):
    """GET with backoff: archive.org refuses connections when you go too fast."""
    waits = [30, 60, 120, 240]
    for i in range(len(waits) + 1):
        try:
            return requests.get(url, headers=HEADERS, timeout=60, **kw)
        except requests.exceptions.ConnectionError:
            if i == len(waits):
                raise
            print(f"    archive.org is rate-limiting, waiting {waits[i]}s...")
            time.sleep(waits[i])


def monthly_snapshots(url, from_year):
    """One successful capture per month. Returns [(timestamp, original_url)]."""
    lookup = url.split("?")[0]                     # archive.org often stores pages without the query
    resp = polite_get("http://web.archive.org/cdx/search/cdx", params={
        "url": lookup, "from": str(from_year), "output": "json",
        "filter": "statuscode:200", "collapse": "timestamp:6",
    })
    try:
        rows = resp.json() if resp.text.strip() else []
    except ValueError:
        print("    archive.org sent a 'slow down' page instead of data - try again in an hour")
        return []
    return [(r[1], r[2]) for r in rows[1:]]


def backfill_service(key, cfg, from_year):
    service = cfg.get('service', key)
    # Apple support pages: use the regional copy that matches the region
    # (old en-in / en-us pages may only show their own country's prices)
    url = cfg['url']
    if "support.apple.com/" in url:
        locale = "en-in" if cfg['region'] == "IN" else "en-us"
        url = re.sub(r'support\.apple\.com/[a-z]{2}-[a-z]{2}/', f'support.apple.com/{locale}/', url)

    stamps = {}
    for ts, original in monthly_snapshots(url, from_year):
        stamps.setdefault(ts[:6], (ts, original))     # one per month
    print(f"\n{key}: {len(stamps)} monthly snapshots found")

    ok = fb = bad = 0
    for month in sorted(stamps):
        ts, u = stamps[month]
        date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        if os.path.exists(f"data/{service}/{cfg['region']}/{date}.json"):
            print(f"  - {date}: already saved")
            continue
        archive_url = f"https://web.archive.org/web/{ts}id_/{u}"
        try:
            html = polite_get(archive_url).text
            plans, how = extract(html, cfg)
            result = {
                "service": service, "region": cfg['region'], "currency": cfg['currency'],
                "scraped_at": f"{date}T00:00:00+00:00", "url": u,
                "source": "wayback", "archive_url": archive_url, "parsed_with": how,
                "plans": plans,
            }
            print(f"  ✓ {date}: {len(plans)} plans ({how}) -> {save_result(result)}")
            ok += how == "strategy"
            fb += how == "fallback"
        except Exception as e:
            print(f"  ✗ {date}: {e}")
            bad += 1
        time.sleep(6)                                  # be polite to archive.org
    return ok, fb, bad


if __name__ == "__main__":
    with open('services_config.json') as f:
        services = json.load(f)
    only = [a for a in sys.argv[1:] if not a.isdigit()]
    years = [int(a) for a in sys.argv[1:] if a.isdigit()]
    from_year = years[0] if years else 2023

    summary = {}
    for key, cfg in services.items():
        if not only or key in only:
            summary[key] = backfill_service(key, cfg, from_year)

    print("\n===== SUMMARY =====")
    for key, (ok, fb, bad) in summary.items():
        print(f"{key:16} saved: {ok + fb:3}  (fallback: {fb})  failed: {bad}")
