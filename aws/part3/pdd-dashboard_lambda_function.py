"""pdd-dashboard — live web dashboard for the Price Drift Detector, served by a Lambda Function URL.

Every page load reads pdd-prices and pdd-alerts straight from DynamoDB, so the dashboard is
always current: a new price shows seconds after pdd-parser loads it, a new alert as soon as
pdd-detector writes it. Replaces Quick Sight (not available on the AWS Free plan).

Shows: price-over-time chart (filter by service + region, one line per plan, alert days
marked), alert counts by type, and a table of all alerts (newest first).

Environment variables:
    PRICES_TABLE  pdd-prices
    ALERTS_TABLE  pdd-alerts
"""
import json
import os
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
PRICES = os.environ.get("PRICES_TABLE", "pdd-prices")
ALERTS = os.environ.get("ALERTS_TABLE", "pdd-alerts")

PRICE_FIELDS = ("series", "date", "service", "region", "plan_name", "currency", "price_value")
ALERT_FIELDS = ("series", "date", "alert_type", "service", "region", "plan_name", "currency",
                "previous_price", "price_value", "change_pct", "rule", "mode")


def plain(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def scan(table_name, fields):
    table = dynamodb.Table(table_name)
    kwargs, rows = {}, []
    while True:
        page = table.scan(**kwargs)
        rows += [{f: plain(item.get(f)) for f in fields} for item in page["Items"]]
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Price Drift Detector</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f6f7f9;color:#1f2937}
 header{background:#111827;color:#fff;padding:16px 24px}
 header h1{margin:0;font-size:20px} header p{margin:4px 0 0;color:#9ca3af;font-size:13px}
 main{max-width:1150px;margin:0 auto;padding:16px}
 .card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:16px}
 .row{display:flex;gap:16px;flex-wrap:wrap}.row>.card{flex:1;min-width:150px}
 .kpi b{display:block;font-size:26px} .kpi span{color:#6b7280;font-size:13px}
 label{font-size:13px;color:#374151;margin-right:12px} select{padding:4px 6px;font-size:14px}
 h2{font-size:15px;margin:0 0 10px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eef0f3} th{background:#f9fafb}
 .t-stealth_hike{color:#b91c1c;font-weight:600}.t-out_of_band{color:#b45309;font-weight:600}.t-shrinkflation{color:#7c3aed;font-weight:600}
 .tablewrap{max-height:420px;overflow:auto}
</style></head><body>
<header><h1>Subscription Price Drift Detector</h1>
<p>Live from DynamoDB &middot; loaded __LOADED__ UTC &middot; refresh the page for the latest data</p></header>
<main>
<div class="row" id="kpis"></div>
<div class="card">
 <h2>Price over time</h2>
 <label>Service <select id="svc"></select></label>
 <label>Region <select id="reg"></select></label>
 <div style="position:relative;height:380px;margin-top:10px"><canvas id="chart"></canvas></div>
 <p style="font-size:12px;color:#6b7280;margin:6px 0 0">Larger points = a day with an alert.</p>
</div>
<div class="card"><h2>Alerts</h2><div class="tablewrap"><table id="alerts"></table></div></div>
</main>
<script>
const PRICES = __PRICES__, ALERTS = __ALERTS__;
const TYPES = {stealth_hike:"Stealth hike", out_of_band:"Unusual price", shrinkflation:"Shrinkflation"};
const SYM = {INR:"₹", USD:"$", EUR:"€"};
const money = (v,c) => v==null ? "" : (SYM[c]||"") + (+v).toLocaleString();
const alertDays = new Set(ALERTS.map(a => a.series + "|" + a.date));

const kpis = [["Price observations", PRICES.length],
  ["Plans tracked", new Set(PRICES.map(p=>p.series)).size],
  ...Object.entries(TYPES).map(([k,l]) => [l + " alerts", ALERTS.filter(a=>a.alert_type===k).length])];
document.getElementById("kpis").innerHTML = kpis.map(([l,v]) =>
  `<div class="card kpi"><b>${v}</b><span>${l}</span></div>`).join("");

const svcSel = document.getElementById("svc"), regSel = document.getElementById("reg");
const services = [...new Set(PRICES.map(p=>p.service))].sort();
svcSel.innerHTML = services.map(s=>`<option>${s}</option>`).join("");
let chart;
function fillRegions(){
  const regs = [...new Set(PRICES.filter(p=>p.service===svcSel.value).map(p=>p.region))].sort();
  regSel.innerHTML = regs.map(r=>`<option>${r}</option>`).join("");
}
function draw(){
  const rows = PRICES.filter(p=>p.service===svcSel.value && p.region===regSel.value);
  const dates = [...new Set(rows.map(r=>r.date))].sort();
  const plans = [...new Set(rows.map(r=>r.plan_name))].sort();
  const cur = rows[0] ? rows[0].currency : "";
  const datasets = plans.map(plan => {
    const byDate = Object.fromEntries(rows.filter(r=>r.plan_name===plan).map(r=>[r.date, r]));
    return {label: plan, spanGaps: true, stepped: true, tension: 0,
      data: dates.map(d => byDate[d] ? byDate[d].price_value : null),
      pointRadius: dates.map(d => byDate[d] && alertDays.has(byDate[d].series+"|"+d) ? 6 : 2)};
  });
  if (chart) chart.destroy();
  chart = new Chart(document.getElementById("chart"), {type:"line", data:{labels:dates, datasets},
    options:{responsive:true, maintainAspectRatio:false, interaction:{mode:"index", intersect:false},
      scales:{y:{title:{display:true, text:"Price (" + cur + ")"}}},
      plugins:{tooltip:{callbacks:{label:c => c.dataset.label + ": " + money(c.parsed.y, cur)}}}}});
}
svcSel.onchange = () => { fillRegions(); draw(); };
regSel.onchange = draw;
fillRegions(); draw();

const sorted = [...ALERTS].sort((a,b) => b.date.localeCompare(a.date));
document.getElementById("alerts").innerHTML =
  "<tr><th>Date</th><th>Type</th><th>Service</th><th>Region</th><th>Plan</th><th>Before</th><th>After</th><th>Change</th><th>Rule</th></tr>" +
  (sorted.length ? sorted.map(a => `<tr><td>${a.date}</td><td class="t-${a.alert_type}">${TYPES[a.alert_type]||a.alert_type}</td>
   <td>${a.service}</td><td>${a.region}</td><td>${a.plan_name}</td><td>${money(a.previous_price,a.currency)}</td>
   <td>${money(a.price_value,a.currency)}</td><td>${a.change_pct==null?"":(a.change_pct>0?"+":"")+a.change_pct.toFixed(1)+"%"}</td>
   <td>${a.rule||""}</td></tr>`).join("") : "<tr><td colspan='9'>No alerts yet.</td></tr>");
</script></body></html>"""


def lambda_handler(event, context):
    from datetime import datetime, timezone
    prices = scan(PRICES, PRICE_FIELDS)
    alerts = scan(ALERTS, ALERT_FIELDS)
    safe = lambda rows: json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    html = (PAGE.replace("__PRICES__", safe(prices))
                .replace("__ALERTS__", safe(alerts))
                .replace("__LOADED__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")))
    return {"statusCode": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
            "body": html}
