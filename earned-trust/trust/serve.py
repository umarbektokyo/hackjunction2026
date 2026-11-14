"""Serve the reviewer page: python -m trust.serve 2283 [--port 8283] [--no-open]

Standard library only. The page reads /api/state and posts decisions to /api/decide.
"""

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import decisions

ROOT = Path(__file__).resolve().parent.parent


def state(issue):
    d = json.loads((ROOT / "dossier" / f"{issue}.json").read_text())
    records = decisions.load(issue)
    return {"dossier": d, "decisions": decisions.latest(records),
            "blockers": decisions.merge_blockers(d, records), "measured": decisions.measured(d, records)}


def decide(issue, item, decision):
    """Record a decision. Who decides and on what evidence comes from the dossier, never from the page."""
    d = json.loads((ROOT / "dossier" / f"{issue}.json").read_text())
    refusal = next((r for r in d["refusals"] if r["id"] == item), None)
    finding = next((f for f in d["findings"] if f["id"] == item), None)
    approver = d["owners"]["approver"]
    if refusal and (decision in refusal["options"] or decision == "reopen"):
        by, evidence = refusal["owner"], refusal["evidence"]
    elif finding and decision in ("real", "not real"):
        by, evidence = approver, finding["checks"]
    elif item == "MERGE" and not decisions.merge_blockers(d, decisions.load(issue)):
        by, evidence, decision = approver, [d["id"]], "approved"
    else:
        raise ValueError(f"not a valid decision: {item} / {decision}")
    decisions.record(issue, d["id"], item, decision, by, evidence)


def handler(issue):
    class Handler(BaseHTTPRequestHandler):
        def send(self, body, kind, code=200):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/state":
                self.send(json.dumps(state(issue)).encode(), "application/json")
            else:
                self.send((ROOT / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                decide(issue, body["item"], body["decision"])
            except (KeyError, ValueError) as e:
                return self.send(str(e).encode(), "text/plain", 400)
            self.send(json.dumps(state(issue)).encode(), "application/json")

        def log_message(self, *args):
            pass

    return Handler


def main():
    args = sys.argv[1:]
    issue = next((a for a in args if a.isdigit()), "2283")
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8283
    url = f"http://localhost:{port}"
    print(f"Earned Trust reviewer for #{issue}: {url}  (Ctrl+C to stop)")
    if "--no-open" not in args:
        webbrowser.open(url)
    ThreadingHTTPServer(("127.0.0.1", port), handler(issue)).serve_forever()


if __name__ == "__main__":
    main()
