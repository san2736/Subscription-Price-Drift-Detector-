"""pdd-alerter — emails every alert in pdd-alerts that hasn't been sent yet, then marks it sent.

Kept separate from pdd-detector so detection can be re-run or tuned without re-sending email.
Invoked by pdd-detector when it records new alerts; can also be run by hand with {}.

Environment variables:
    ALERTS_TABLE  pdd-alerts
    TOPIC_ARN     arn:aws:sns:ap-south-1:<account-id>:pdd-alerts
"""
import json
import os

import boto3
from boto3.dynamodb.conditions import Attr

alerts = boto3.resource("dynamodb").Table(os.environ.get("ALERTS_TABLE", "pdd-alerts"))
sns = boto3.client("sns")
SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€"}
LABEL = {"stealth_hike": "STEALTH HIKE", "out_of_band": "UNUSUAL PRICE", "shrinkflation": "SHRINKFLATION"}


def money(value, currency):
    return f"{SYMBOL.get(currency, currency + ' ')}{float(value):,.2f}".replace(".00", "")


def describe(a):
    line = (f"{LABEL.get(a['alert_type'], a['alert_type'])}: {a['service']} {a['region']} "
            f"{a['plan_name']} on {a['date']}: {money(a['previous_price'], a['currency'])} -> "
            f"{money(a['price_value'], a['currency'])}")
    if a.get("change_pct") is not None:
        line += f" ({float(a['change_pct']):+.1f}%)"
    line += f"\n    rule: {a.get('rule', '')}"
    if a.get("expected_mean") is not None:
        if float(a["expected_std"]) == 0:
            line += f"; price had been flat at {money(a['expected_mean'], a['currency'])}"
        else:
            line += (f"; expected about {money(a['expected_mean'], a['currency'])}"
                     f" ± {money(2 * float(a['expected_std']), a['currency'])}")
    before, after = a.get("storage_before"), a.get("storage_after")
    if before is not None and after is not None and float(before) != float(after):
        line += f"; storage {float(before):g} GB -> {float(after):g} GB"
    return line


def lambda_handler(event, context):
    pending, kwargs = [], {"FilterExpression": Attr("notified").eq(False)}
    while True:
        page = alerts.scan(**kwargs)
        pending.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    if not pending:
        print(json.dumps({"sent": 0}))
        return {"sent": 0}

    pending.sort(key=lambda a: (a["date"], a["series"]))
    body = ("Subscription Price Drift Detector found "
            f"{len(pending)} new alert(s):\n\n" + "\n\n".join(describe(a) for a in pending) +
            "\n\nAll alerts: DynamoDB table pdd-alerts, or the QuickSight dashboard.")
    subject = f"Price Drift Detector: {len(pending)} new alert(s)"
    sns.publish(TopicArn=os.environ["TOPIC_ARN"], Subject=subject, Message=body)

    for a in pending:
        alerts.update_item(Key={"series": a["series"], "alert_id": a["alert_id"]},
                           UpdateExpression="SET notified = :t", ExpressionAttributeValues={":t": True})
    print(json.dumps({"sent": len(pending)}))
    return {"sent": len(pending)}
