"""Per-order profit of an ended world: python analyse.py <world id>"""
import sys, json, glob, subprocess, pandas as pd
wid = sys.argv[1]
d = f"logs/reveal-{wid}"
if not glob.glob(d):
    subprocess.run([sys.executable, "-c", "from spread.reveal_csv import main; import sys; sys.argv=['x', sys.argv[1]]; main()", wid], cwd="logs", check=True, capture_output=True)
r = pd.read_csv(f"{d}/requests.csv"); lg = pd.read_csv(f"{d}/legs.csv"); ev = pd.read_csv(f"{d}/events.csv", low_memory=False)
led = ev[ev.kind == "ledger"]
per = led.groupby(["line.orderId", "line.kind"])["line.cents"].sum().unstack(fill_value=0)
w = r[r.outcome == "won"].set_index("id")
first = lg[lg.leg == 0].set_index("requestId")
df = per.join(w[["referenceFeeCents", "option", "dealerId"]]).join(first[["pickup.placeId", "delivery.placeId", "pickup.privateAddress", "delivery.privateAddress"]])
df["margin"] = per.sum(axis=1)
df["price_ref"] = df.get("revenue", 0) / df.referenceFeeCents
df["fee_ref"] = -df.get("driver_fee", 0) / df.referenceFeeCents
print("orders", len(df), "margin €", df.margin.sum() / 100)
print((per.sum() / 100).round(0).to_dict())
print("fee/ref", df.fee_ref.describe().round(2).to_dict())
print("price/ref", df.price_ref.describe().round(2).to_dict())
for col in ["option", "pickup.placeId", "delivery.placeId"]:
    g = df.groupby(col).agg(n=("margin", "size"), margin=("margin", "sum"), fee_ref=("fee_ref", "mean")).sort_values("margin")
    g["margin"] /= 100
    print(g.round(2).to_string())
