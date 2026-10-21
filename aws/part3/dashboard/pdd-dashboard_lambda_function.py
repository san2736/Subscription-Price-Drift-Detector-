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
 :root{--bg:#aebbd0;--navy:#1d2740;--navy2:#2a3a5f;--card:#eef2f8;--ink:#1d2740;--muted:#6b7895;--teal:#3fb6b2;--cyan:#56c8e8;--blue:#3b6fb6;--line:#d5dce8}
 *{box-sizing:border-box} body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}
 .frame{max-width:1220px;margin:24px auto;background:#c9d3e3;border-radius:22px;overflow:hidden;box-shadow:0 18px 40px rgba(29,39,64,.25)}
 nav{background:var(--navy);color:#fff;display:flex;align-items:center;gap:18px;padding:14px 26px;flex-wrap:wrap}
 nav h1{font-size:18px;margin:0 18px 0 0;font-weight:700;letter-spacing:.2px}
 nav .pill{text-decoration:none;border:1px solid #5d6f96;border-radius:999px;padding:5px 16px;font-size:12px;color:#c9d3e3}
 nav .pill.on{border-color:var(--cyan);color:#fff;box-shadow:0 0 0 1px var(--cyan) inset}
 nav .stamp{margin-left:auto;font-size:12px;color:#8fa0c4}
 .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:18px;padding:20px}
 .card{background:var(--card);border-radius:16px;padding:16px 18px;box-shadow:0 6px 16px rgba(29,39,64,.12)}
 .dark{background:linear-gradient(160deg,var(--navy2),var(--navy));color:#fff}
 h2{font-size:14px;margin:0 0 10px;font-weight:700} .dark h2{color:#fff}
 .big{font-size:34px;font-weight:700;margin:2px 0} .sub{font-size:12px;color:var(--muted)} .dark .sub{color:#9fb0d3}
 .kpis{display:flex;gap:10px;margin-top:14px} .kpis div{flex:1;background:rgba(255,255,255,.07);border-radius:10px;padding:8px 10px}
 .kpis b{display:block;font-size:20px} .kpis span{font-size:11px;color:#9fb0d3}
 .c3{grid-column:span 3}.c4{grid-column:span 4}.c5{grid-column:span 5}.c8{grid-column:span 8}.c9{grid-column:span 9}.c12{grid-column:span 12}
 @media(max-width:900px){.c3,.c4,.c5,.c8,.c9{grid-column:span 12}}
 .filters{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
 select{border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 12px;font-size:13px;color:var(--ink)}
 .legend{list-style:none;padding:0;margin:10px 0 0;font-size:12px} .legend li{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--line)}
 .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
 table{width:100%;border-collapse:collapse;font-size:12.5px} th{color:#9fb0d3;font-weight:600;text-align:left;padding:7px 8px;border-bottom:1px solid #3a4a70;position:sticky;top:0;background:var(--navy)}
 td{padding:7px 8px;border-bottom:1px solid #2f3e63;color:#e6ecf7} .wrap{max-height:380px;overflow:auto}
 table.light th{background:#e3e9f3;color:#6b7895;border-bottom:1px solid var(--line);position:static} table.light td{color:var(--ink);border-bottom:1px solid var(--line)}
 .tag{border-radius:999px;padding:2px 9px;font-size:11px;font-weight:600}
 .t-stealth_hike{background:#5b2b3b;color:#ff9fb4}.t-out_of_band{background:#173f53;color:#7fdcff}.t-shrinkflation{background:#3d2f5c;color:#c7b3ff}
 .tab{display:none} .tab.on{display:contents} nav .pill{cursor:pointer}
 .c6{grid-column:span 6} @media(max-width:900px){.c6{grid-column:span 12}}
 .form{display:flex;flex-wrap:wrap;gap:8px} .form input{border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:13px;width:150px}
 .form button{background:var(--navy);color:#fff;border:0;border-radius:999px;padding:7px 18px;font-size:13px;cursor:pointer} .form button:hover{background:var(--blue)}
 .result{margin-top:14px;font-size:14px;line-height:1.5;min-height:60px} .verdict{font-size:20px;font-weight:700;margin-bottom:4px}
 .ok{color:#1f8f6a}.warn{color:#c2410c}.info{color:var(--blue)} .result .big{font-size:30px}
 table.heat{border-collapse:separate;border-spacing:2px;font-size:10px} table.heat th{background:none;color:var(--muted);font-weight:600;position:static;border:0;padding:2px 4px;white-space:nowrap}
 table.heat td{min-width:12px;width:12px;height:20px;border-radius:4px;font-size:9.5px;padding:0;border:0;text-align:center;color:#fff;font-weight:600}
 #tip{position:fixed;display:none;z-index:10;background:var(--navy);color:#fff;font-size:12px;line-height:1.5;padding:8px 11px;border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.25);pointer-events:none;max-width:280px}
 .up{color:#ff9fb4}.down{color:#7fe3c4}
</style></head><body><div id="tip"></div><div class="frame">
<nav><h1>&#9650; Price Drift Detector</h1><a class="pill on" href="#dashboard" data-tab="dashboard">Dashboard</a><a class="pill" href="#prices" data-tab="prices">Prices</a><a class="pill" href="#alerts" data-tab="alerts">Alerts</a><a class="pill" href="#tools" data-tab="tools">Am I charged correctly?</a>
<span class="stamp">Live from DynamoDB &middot; __LOADED__ UTC</span></nav>
<div class="grid">
 <div class="tab on" id="tab-dashboard">
  <div class="card dark c4" id="hero"></div>
  <div class="card c5"><h2>Alerts by service</h2><div style="height:200px"><canvas id="bars"></canvas></div></div>
  <div class="card c3"><h2>Alert types</h2><div style="height:150px"><canvas id="donut"></canvas></div><ul class="legend" id="leg"></ul></div>
  <div class="card c12"><h2>Hike calendar</h2><div class="sub" style="margin:-6px 0 10px">Alerts per service per month. Darker = more alerts. Hover a cell for details.</div><div style="overflow-x:auto"><table id="heat" class="heat"></table></div></div>
  <div class="card dark c12"><h2>Latest alerts</h2><table id="recent"></table></div>
 </div>
 <div class="tab" id="tab-prices">
  <div class="card c12"><div class="filters"><h2 style="margin:0 10px 0 0">Price over time</h2>
   <select id="svc"></select><select id="reg"></select><span class="sub">Larger points mark alert days</span></div>
   <div style="height:360px"><canvas id="chart"></canvas></div></div>
  <div class="card c12"><h2 id="curTitle">Current prices</h2><table id="current" class="light"></table></div>
 </div>
 <div class="tab" id="tab-tools">
  <div class="card c6"><h2>Check my bill</h2><div class="sub" style="margin:-6px 0 12px">Pick your plan and enter what you were actually charged.</div>
   <div class="form"><select id="bSvc"></select><select id="bReg"></select><select id="bPlan"></select>
   <input id="bAmt" type="number" step="0.01" min="0" placeholder="Amount charged"><button id="bGo">Check</button></div>
   <div id="bOut" class="result"></div></div>
  <div class="card c6"><h2>What the hikes cost you</h2><div class="sub" style="margin:-6px 0 12px">Total paid since a start month vs. if the price had never changed.</div>
   <div class="form"><select id="cSvc"></select><select id="cReg"></select><select id="cPlan"></select>
   <input id="cStart" type="month"><button id="cGo">Calculate</button></div>
   <div id="cOut" class="result"></div></div>
 </div>
 <div class="tab" id="tab-alerts">
  <div class="card dark c12"><div class="filters"><h2 style="margin:0 10px 0 0">All alerts</h2>
   <select id="ftype"><option value="">All types</option></select><select id="fsvc"><option value="">All services</option></select>
   <span class="sub" id="fcount"></span></div>
   <div class="wrap" style="max-height:620px"><table id="alerts"></table></div></div>
 </div>
</div></div>
<script>
const PRICES = __PRICES__, ALERTS = __ALERTS__;
const TYPES = {stealth_hike:"Stealth hike", out_of_band:"Unusual price", shrinkflation:"Shrinkflation"};
const TCOL = {stealth_hike:"#e8607f", out_of_band:"#56c8e8", shrinkflation:"#8b7ae0"};
const PAL = ["#3fb6b2","#3b6fb6","#56c8e8","#1d2740","#8b7ae0","#e8607f","#f0b44c"];
const SYM = {INR:"₹", USD:"$", EUR:"€"};
const money = (v,c) => v==null ? "" : (SYM[c]||"") + (+v).toLocaleString();
Chart.defaults.font.family = "Inter,system-ui,sans-serif"; Chart.defaults.color = "#6b7895";
const alertDays = new Set(ALERTS.map(a => a.series + "|" + a.date));
const sorted = [...ALERTS].sort((a,b) => b.date.localeCompare(a.date));
const latest = sorted[0];
document.getElementById("hero").innerHTML = `<h2>Overview</h2>
 <div class="big">${ALERTS.length}</div><div class="sub">price alerts detected</div>
 <div class="kpis"><div><b>${PRICES.length.toLocaleString()}</b><span>prices tracked</span></div>
 <div><b>${new Set(PRICES.map(p=>p.series)).size}</b><span>plans</span></div>
 <div><b>${new Set(PRICES.map(p=>p.service)).size}</b><span>services</span></div></div>
 <div class="sub" style="margin-top:14px">Latest: ${latest ? `${latest.service} ${latest.region} ${latest.plan_name}, ${latest.date} (${TYPES[latest.alert_type]})` : "none yet"}</div>`;
const counts = Object.keys(TYPES).map(k => ALERTS.filter(a=>a.alert_type===k).length);
new Chart(document.getElementById("donut"), {type:"doughnut", data:{labels:Object.values(TYPES),
  datasets:[{data:counts, backgroundColor:Object.values(TCOL), borderWidth:0}]},
  options:{cutout:"68%", plugins:{legend:{display:false}}, maintainAspectRatio:false}});
document.getElementById("leg").innerHTML = Object.keys(TYPES).map((k,i)=>`<li><span><span class="dot" style="background:${TCOL[k]}"></span>${TYPES[k]}</span><b>${counts[i]}</b></li>`).join("");
const svcs = [...new Set(ALERTS.map(a=>a.service))].sort();
new Chart(document.getElementById("bars"), {type:"bar", data:{labels:svcs,
  datasets:Object.keys(TYPES).map(k=>({label:TYPES[k], backgroundColor:TCOL[k], borderRadius:6,
    data:svcs.map(s=>ALERTS.filter(a=>a.service===s&&a.alert_type===k).length)}))},
  options:{maintainAspectRatio:false, scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:"#d5dce8"}}},
    plugins:{legend:{position:"bottom",labels:{boxWidth:10}}}}});
const svcSel = document.getElementById("svc"), regSel = document.getElementById("reg");
svcSel.innerHTML = [...new Set(PRICES.map(p=>p.service))].sort().map(s=>`<option>${s}</option>`).join("");
let chart;
function fillRegions(){ regSel.innerHTML = [...new Set(PRICES.filter(p=>p.service===svcSel.value).map(p=>p.region))].sort().map(r=>`<option>${r}</option>`).join(""); }
function draw(){
  const rows = PRICES.filter(p=>p.service===svcSel.value && p.region===regSel.value);
  const dates = [...new Set(rows.map(r=>r.date))].sort(), plans = [...new Set(rows.map(r=>r.plan_name))].sort();
  const cur = rows[0] ? rows[0].currency : "";
  const datasets = plans.map((plan,i) => { const by = Object.fromEntries(rows.filter(r=>r.plan_name===plan).map(r=>[r.date,r]));
    return {label:plan, spanGaps:true, stepped:true, borderColor:PAL[i%PAL.length], backgroundColor:PAL[i%PAL.length], borderWidth:2.5,
      data:dates.map(d=>by[d]?by[d].price_value:null), pointRadius:dates.map(d=>by[d]&&alertDays.has(by[d].series+"|"+d)?7:0)}; });
  if (chart) chart.destroy();
  chart = new Chart(document.getElementById("chart"), {type:"line", data:{labels:dates, datasets},
    options:{maintainAspectRatio:false, interaction:{mode:"index",intersect:false},
      scales:{x:{grid:{display:false},ticks:{maxTicksLimit:14}}, y:{grid:{color:"#d5dce8"}, title:{display:true,text:"Price ("+cur+")"}}},
      plugins:{legend:{position:"top",labels:{boxWidth:10}}, tooltip:{callbacks:{label:c=>c.dataset.label+": "+money(c.parsed.y,cur)}}}}});
}
svcSel.onchange = () => { fillRegions(); draw(); drawCurrent(); }; regSel.onchange = () => { draw(); drawCurrent(); }; fillRegions();
const HEAD = "<tr><th>Date</th><th>Type</th><th>Service</th><th>Region</th><th>Plan</th><th>Before</th><th>After</th><th>Change</th><th>Rule</th></tr>";
const row = a => `<tr><td>${a.date}</td><td><span class="tag t-${a.alert_type}">${TYPES[a.alert_type]||a.alert_type}</span></td>
  <td>${a.service}</td><td>${a.region}</td><td>${a.plan_name}</td><td>${money(a.previous_price,a.currency)}</td><td>${money(a.price_value,a.currency)}</td>
  <td class="${a.change_pct>0?"up":"down"}">${a.change_pct==null?"":(a.change_pct>0?"+":"")+a.change_pct.toFixed(1)+"%"}</td><td>${a.rule||""}</td></tr>`;
const empty = "<tr><td colspan='9'>No alerts yet.</td></tr>";
document.getElementById("recent").innerHTML = HEAD + (sorted.length ? sorted.slice(0,6).map(row).join("") : empty);
const ftype = document.getElementById("ftype"), fsvc = document.getElementById("fsvc");
ftype.innerHTML += Object.entries(TYPES).map(([k,l])=>`<option value="${k}">${l}</option>`).join("");
fsvc.innerHTML += svcs.map(s=>`<option>${s}</option>`).join("");
function drawAlerts(){
  const rows = sorted.filter(a => (!ftype.value || a.alert_type===ftype.value) && (!fsvc.value || a.service===fsvc.value));
  document.getElementById("alerts").innerHTML = HEAD + (rows.length ? rows.map(row).join("") : empty);
  document.getElementById("fcount").textContent = rows.length + " alert" + (rows.length===1?"":"s");
}
ftype.onchange = drawAlerts; fsvc.onchange = drawAlerts; drawAlerts();
function drawCurrent(){
  const rows = PRICES.filter(p=>p.service===svcSel.value && p.region===regSel.value);
  const last = {}; rows.forEach(r => { if (!last[r.plan_name] || r.date > last[r.plan_name].date) last[r.plan_name] = r; });
  document.getElementById("curTitle").textContent = `Current prices: ${svcSel.value} ${regSel.value}`;
  document.getElementById("current").innerHTML = "<tr><th>Plan</th><th>Latest price</th><th>As of</th><th>Alerts on this plan</th></tr>" +
    Object.values(last).sort((a,b)=>a.price_value-b.price_value).map(r => `<tr><td>${r.plan_name}</td><td>${money(r.price_value,r.currency)}</td><td>${r.date}</td>
    <td>${ALERTS.filter(a=>a.series===r.series).length}</td></tr>`).join("");
}
// ---------- Hike calendar ----------
(function(){
  const months = [...new Set(ALERTS.map(a=>a.date.slice(0,7)))].sort();
  if (!months.length) { document.getElementById("heat").innerHTML = "<tr><td>No alerts yet.</td></tr>"; return; }
  const all = []; let [y,m] = months[0].split("-").map(Number); const [ly,lm] = months.at(-1).split("-").map(Number);
  while (y<ly || (y===ly && m<=lm)) { all.push(`${y}-${String(m).padStart(2,"0")}`); m++; if (m>12){m=1;y++;} }
  const cnt = {}; ALERTS.forEach(a => { const k=a.service+"|"+a.date.slice(0,7); (cnt[k]=cnt[k]||[]).push(a); });
  const max = Math.max(...Object.values(cnt).map(v=>v.length));
  const MON = ["J","F","M","A","M","J","J","A","S","O","N","D"];
  let html = "<tr><th></th>" + all.map(k => `<th title="${k}" style="padding:2px 0">${k.endsWith("-01") ? "'"+k.slice(2,4) : k.endsWith("-07") ? "Jul" : ""}</th>`).join("") + "</tr>";
  svcs.forEach(s => {
    html += `<tr><th style="text-align:right">${s}</th>` + all.map(k => { const v = cnt[s+"|"+k] || [];
      const t = v.length ? `${s} ${k}: ${v.length} alert(s)\\n` + v.map(a=>`${a.plan_name} ${a.region}: ${TYPES[a.alert_type]}`).join("\\n") : `${s} ${k}: none`;
      const bg = v.length ? `rgba(232,96,127,${0.35+0.65*v.length/max})` : "#e3e9f3";
      return `<td data-tip="${t}" style="background:${bg};cursor:${v.length?"pointer":"default"}">${v.length||""}</td>`; }).join("") + "</tr>";
  });
  const heat = document.getElementById("heat"); heat.innerHTML = html;
  const tip = document.getElementById("tip");
  const show = (td, x, y) => { tip.innerHTML = td.dataset.tip.split("\\n").map((l,i)=>i?l:`<b>${l}</b>`).join("<br>");
    tip.style.display = "block"; tip.style.left = Math.min(x+14, innerWidth-tip.offsetWidth-10)+"px"; tip.style.top = (y+14)+"px"; };
  heat.addEventListener("mousemove", e => { const td = e.target.closest("td[data-tip]"); td ? show(td, e.clientX, e.clientY) : tip.style.display = "none"; });
  heat.addEventListener("mouseleave", () => tip.style.display = "none");
  heat.addEventListener("click", e => { const td = e.target.closest("td[data-tip]"); if (td) show(td, e.clientX, e.clientY); });
})();
// ---------- shared plan pickers ----------
const SERIES = {}; PRICES.forEach(p => (SERIES[p.series] = SERIES[p.series] || []).push(p));
Object.values(SERIES).forEach(v => v.sort((a,b)=>a.date.localeCompare(b.date)));
function picker(sv, rg, pl){
  const S = document.getElementById(sv), R = document.getElementById(rg), P = document.getElementById(pl);
  S.innerHTML = [...new Set(PRICES.map(p=>p.service))].sort().map(x=>`<option>${x}</option>`).join("");
  const fillR = () => { R.innerHTML = [...new Set(PRICES.filter(p=>p.service===S.value).map(p=>p.region))].sort().map(x=>`<option>${x}</option>`).join(""); fillP(); };
  const fillP = () => { P.innerHTML = [...new Set(PRICES.filter(p=>p.service===S.value&&p.region===R.value).map(p=>p.plan_name))].sort().map(x=>`<option>${x}</option>`).join(""); };
  S.onchange = fillR; R.onchange = fillP; fillR();
  return () => `${S.value}#${R.value}#${P.value}`;
}
const fmtDate = d => new Date(d+"T00:00:00Z").toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"});
// ---------- Check my bill ----------
const billSeries = picker("bSvc","bReg","bPlan");
document.getElementById("bGo").onclick = () => {
  const rows = SERIES[billSeries()] || [], out = document.getElementById("bOut");
  const amt = parseFloat(document.getElementById("bAmt").value);
  if (!rows.length) { out.innerHTML = "No price data for this plan."; return; }
  if (isNaN(amt)) { out.innerHTML = "Enter the amount you were charged."; return; }
  const last = rows.at(-1), cur = last.currency, listed = last.price_value, diff = amt - listed;
  let change = null; for (let i = rows.length-1; i > 0; i--) if (rows[i].price_value !== rows[i-1].price_value) { change = [rows[i-1], rows[i]]; break; }
  const tol = Math.max(0.01, listed*0.01);
  let verdict;
  if (Math.abs(diff) <= tol) verdict = `<div class="verdict ok">&#10003; Correct</div>You're paying the listed price of ${money(listed,cur)}.`;
  else if (diff > 0) verdict = `<div class="verdict warn">&#9888; Overcharged by ${money(diff.toFixed(2),cur)}</div>The listed price is ${money(listed,cur)} (as of ${fmtDate(last.date)}). Check for taxes, add-ons, or an old plan.`;
  else verdict = `<div class="verdict info">&#8595; ${money((-diff).toFixed(2),cur)} below the listed price</div>You may be on an older price, a promo or a discount. The listed price is now ${money(listed,cur)}.`;
  if (change) { const pct = (change[1].price_value-change[0].price_value)/change[0].price_value*100;
    verdict += `<div class="sub" style="margin-top:8px">Last price change: ${money(change[0].price_value,cur)} &rarr; ${money(change[1].price_value,cur)} (${pct>0?"+":""}${pct.toFixed(1)}%) between ${fmtDate(change[0].date)} and ${fmtDate(change[1].date)}.</div>`; }
  else verdict += `<div class="sub" style="margin-top:8px">No price change recorded since ${fmtDate(rows[0].date)}.</div>`;
  out.innerHTML = verdict;
};
// ---------- What the hikes cost you ----------
const costSeries = picker("cSvc","cReg","cPlan");
document.getElementById("cGo").onclick = () => {
  const rows = SERIES[costSeries()] || [], out = document.getElementById("cOut");
  const start = document.getElementById("cStart").value;
  if (!rows.length) { out.innerHTML = "No price data for this plan."; return; }
  if (!start) { out.innerHTML = "Choose a start month."; return; }
  const name = rows[0].plan_name.toLowerCase(), cur = rows[0].currency;
  const step = name.includes("annual") ? 12 : name.includes("6 months") ? 6 : name.includes("quarterly") ? 3 : 1;
  const priceAt = ym => { let p = null; for (const r of rows) { if (r.date.slice(0,7) <= ym) p = r.price_value; else break; } return p; };
  const endYm = rows.at(-1).date.slice(0,7);
  let [y,m] = start.split("-").map(Number); let ym = start, base = priceAt(start);
  if (base === null) { base = rows[0].price_value; ym = rows[0].date.slice(0,7); [y,m] = ym.split("-").map(Number); }
  let paid = 0, wouldPay = 0, bills = 0;
  while (ym <= endYm) { const p = priceAt(ym); paid += p; wouldPay += base; bills++;
    m += step; while (m > 12) { m -= 12; y++; } ym = `${y}-${String(m).padStart(2,"0")}`; }
  const extra = paid - wouldPay, period = {1:"monthly",3:"quarterly",6:"6-monthly",12:"annual"}[step];
  out.innerHTML = `<div class="verdict ${extra>0?"warn":extra<0?"ok":"info"}"><span class="big">${extra>=0?"":"-"}${money(Math.abs(extra).toFixed(2),cur)}</span> ${extra>0?"extra paid":extra<0?"saved":"no difference"}</div>
    ${bills} ${period} payment${bills===1?"":"s"} from ${start} to ${endYm}: you paid ${money(paid.toFixed(2),cur)}; at the ${start} price of ${money(base,cur)} it would have been ${money(wouldPay.toFixed(2),cur)}.
    <div class="sub" style="margin-top:8px">Uses the price on record for each billing month; actual bills may include taxes.</div>`;
};
function showTab(name){
  if (!document.getElementById("tab-"+name)) name = "dashboard";
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t.id==="tab-"+name));
  document.querySelectorAll("nav .pill").forEach(p => p.classList.toggle("on", p.dataset.tab===name));
  if (name==="prices") { draw(); drawCurrent(); }
}
document.querySelectorAll("nav .pill").forEach(p => p.onclick = e => { e.preventDefault(); history.replaceState(null,"","#"+p.dataset.tab); showTab(p.dataset.tab); });
showTab(location.hash.slice(1) || "dashboard");
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
