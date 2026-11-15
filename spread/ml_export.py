"""Exports the reveal of every ended level 8 practice world (not a ranking run) into logs/reveal-<id>/.
Skips worlds already exported. Run: . ./env.sh && "$SPREAD_PYTHON" ml_export.py"""
import os, subprocess, sys, time
from spread.client import Client

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
ws = [w for w in Client().worlds() if w["kind"] == "practice" and w["level"] == 8 and w["ended"] and w["boardRun"] is None]
todo = [w["worldId"] for w in ws if not os.path.exists(os.path.join(LOGS, f"reveal-{w['worldId']}", "roads.csv"))]
print(f"{len(ws)} ended practice worlds, {len(todo)} to export", flush=True)
for i, wid in enumerate(todo):
    for attempt in range(3):
        r = subprocess.run([sys.executable, "-c", "from spread.reveal_csv import main; main()", wid], cwd=LOGS, capture_output=True, text=True)
        if r.returncode == 0:
            break
        print(wid, "retry", r.stderr[-200:], flush=True)
        time.sleep(5)
    print(f"{i+1}/{len(todo)} {wid} {'ok' if r.returncode == 0 else 'FAILED'}", flush=True)
