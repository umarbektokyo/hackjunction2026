#!/bin/bash
# Plays this round's 5 level 8 ranking runs with the best fee-clock setting from logs/bench.jsonl.
cd "$(dirname "$0")"; . ./env.sh
while pgrep -f sweep.sh >/dev/null; do sleep 5; done
P=$(../.venv/bin/python - <<'PY'
import json
best=None
for l in open("logs/bench.jsonl"):
    r=json.loads(l)
    if r["name"] not in ("clock","clock9"): continue
    rows=[x for x in r["rows"] if "marginCents" in x]
    if len(rows)<8 or not all(x["ranked"] for x in rows): continue
    m=sum(x["marginCents"] for x in rows)/len(rows)
    if best is None or m>best[0]: best=(m,r["name"],r["params"])
print(json.dumps(best[2])); import sys; print(best[1], round(best[0]/100), file=sys.stderr)
PY
)
echo "params $P"
for i in 1 2 3 4 5; do ../.venv/bin/python bot.py --board --params "$P" --quiet --json & sleep 2; done
wait
