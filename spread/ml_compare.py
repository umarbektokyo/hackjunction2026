"""Prints the with/without table of the learned-model benches from logs/bench.jsonl.
    ../.venv/bin/python ml_compare.py [name ...]        default: clock ml ml-win ml-fee base-oos ml-oos
For each bench: mean margin per week, weeks ranked, mean and worst on-time share, mean orders and margin per order,
and the margin per seed. A name used more than once means its latest entry."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:] or ["clock", "ml", "ml-win", "ml-fee", "base-oos", "ml-oos"]
last = {}
for line in open(os.path.join(HERE, "logs", "bench.jsonl")):
    r = json.loads(line)
    if r["name"] in names:
        last[r["name"]] = r
print(f"{'bench':<10} {'bot':<8} {'€/week':>8} {'ranked':>7} {'on time':>8} {'worst':>6} {'orders':>7} {'€/order':>8}  per seed (€)")
for n in names:
    if n not in last:
        continue
    r = last[n]
    rows = [x for x in r["rows"] if "marginCents" in x]
    if not rows:
        continue
    k = len(rows)
    m = sum(x["marginCents"] for x in rows) / k / 100
    o = sum(x["wonOrders"] for x in rows) / k
    per = "  ".join(f"{x['seed'].replace('bench-', 's')}:{x['marginCents'] / 100:,.0f}" for x in sorted(rows, key=lambda x: int(x["seed"].split("-")[-1])))
    print(f"{n:<10} {r.get('bot', 'bot.py'):<8} {m:>8,.0f} {sum(x['ranked'] for x in rows):>4}/{k:<2} {sum(x['onTimeShare'] for x in rows) / k:>8.1%} "
          f"{min(x['onTimeShare'] for x in rows):>6.1%} {o:>7.0f} {m / o:>8.1f}  {per}")
