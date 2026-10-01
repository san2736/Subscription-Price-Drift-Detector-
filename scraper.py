import json, re, os, requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone


# ---------- Netflix-style: features in a table, prices in a separate bullet list ----------
def scrape_table_plus_list(soup, config):
    tables = soup.find_all('table')
    plans_table = tables[config['table_index']]
    rows = plans_table.find_all('tr')
    plans = {}
    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) >= 2:
            name = cells[0].get_text(strip=True)
            features = cells[1].get_text(separator=' | ', strip=True)
            plans[name] = {"plan_name": name, "features": features, "price_raw": None,
                           "price_value": None, "currency": config['currency']}
    price_heading = soup.find(string=re.compile(config['price_heading_regex'], re.I))
    if price_heading:
        price_list = price_heading.find_parent().find_next('ul')
        if price_list:
            for li in price_list.find_all('li'):
                text = li.get_text(strip=True)
                match = re.match(r'([A-Za-z]+):\s*(₹[\d,]+)\s*INR/month', text)
                if match:
                    plan_name, price = match.groups()
                    if plan_name in plans:
                        plans[plan_name]['price_raw'] = price
                        plans[plan_name]['price_value'] = parse_price(price)
    return list(plans.values())


# ---------- Generic: plan name + price in predictable repeating elements ----------
def scrape_simple_selector(soup, config):
    plan_els = soup.select(config['plan_selector'])
    price_els = soup.select(config['price_selector'])
    plans = []
    for name_el, price_el in zip(plan_els, price_els):
        price_text = price_el.get_text(strip=True)
        plans.append({
            "plan_name": name_el.get_text(strip=True),
            "features": "",
            "price_raw": price_text,
            "price_value": parse_price(price_text),
            "currency": config['currency']
        })
    return plans


# ---------- ADD YOUR STRATEGY FUNCTIONS HERE (same shape: soup, config -> list of plans) ----------

# ---------- iCloud+: country rows in Apple's pricing tables ----------
def scrape_icloud_table(soup, config):
    country = config['country']                      # e.g. "India" or "United States"
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows:
            continue
        # Header row: "Country (Currency)", "50 GB", "200 GB", "2 TB", "6 TB", "12 TB"
        tiers = [c.get_text(strip=True) for c in rows[0].find_all(['th', 'td'])][1:]
        for row in rows[1:]:
            cells = row.find_all(['th', 'td'])
            name = cells[0].get_text(strip=True)     # e.g. "India³ (INR)"
            # match the country name exactly, ignoring footnote marks like ³
            if not re.match(rf'^{re.escape(country)}[^A-Za-z]', name + " "):
                continue
            plans = []
            for tier, cell in zip(tiers, cells[1:]):
                price_text = cell.get_text(strip=True)   # e.g. "Rs 75"
                size = parse_price(tier)                 # 50, 200, 2, 6, 12
                storage_gb = size * 1000 if "TB" in tier else size
                plans.append({
                    "plan_name": f"iCloud+ {tier}",
                    "features": tier,
                    "storage_gb": storage_gb,
                    "price_raw": price_text,
                    "price_value": parse_price(price_text),
                    "currency": config['currency']
                })
            return plans
    raise ValueError(f"country '{country}' not found in any pricing table")
# Register every strategy here
STRATEGIES = {
    "table_plus_list": scrape_table_plus_list,
    "simple_selector": scrape_simple_selector,
    "icloud_table": scrape_icloud_table,
}


# ADDED: one price parser for everyone, works for ₹ and $ ("₹1,499" -> 1499.0, "$10.99" -> 10.99)
def parse_price(text):
    match = re.search(r'\d[\d,]*(?:\.\d+)?', text or "")
    return float(match.group().replace(',', '')) if match else None


def scrape_service(service_name, config):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(config['url'], headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    plans = STRATEGIES[config['method']](soup, config)
    return {
        "service": config.get('service', service_name),
        "region": config['region'],
        "currency": config['currency'],                              # ADDED
        "scraped_at": datetime.now(timezone.utc).isoformat(),        # CHANGED: utcnow() is deprecated
        "url": config['url'],
        "plans": plans
    }


# ADDED: save each result to data/{service}/{region}/{date}.json (same layout as S3 later)
def save_result(result):
    folder = f"data/{result['service']}/{result['region']}"
    os.makedirs(folder, exist_ok=True)
    path = f"{folder}/{result['scraped_at'][:10]}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return path


if __name__ == "__main__":
    with open('services_config.json') as f:
        services = json.load(f)

    for name, cfg in services.items():
        try:
            result = scrape_service(name, cfg)
            path = save_result(result)
            print(f"✓ {name}: {len(result['plans'])} plans found -> {path}")
        except Exception as e:
            print(f"✗ {name} failed: {e}")
