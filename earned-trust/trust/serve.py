"""Serve the reviewer: python -m trust.serve [--port 8283] [--no-open]

Standard library only. Every built dossier is a case the page can switch to:
GET /api/cases, GET /api/state?case=<id>, POST /api/decide {case, item, decision, note}.
Everything else is a static file from web/.
"""

import json
import mimetypes
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import decisions

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def dossier(case):
    return json.loads((ROOT / "dossier" / f"{case}.json").read_text())


def cases():
    """The built cases, for the switcher: id, label, title, language and how many decisions are open."""
    out = []
    for path in sorted((ROOT / "dossier").glob("*.json")):
        d, done = json.loads(path.read_text()), decisions.latest(decisions.load(path.stem))
        c = d["case"]
        out.append({"id": path.stem, "label": c.get("label", f"#{c['issue']}"), "title": c["title"],
                    "language": c.get("language", ""), "open": sum(r["id"] not in done for r in d["refusals"]),
                    "outcome": done.get("MERGE", {}).get("decision")})
    return out


def state(case):
    d, records = dossier(case), decisions.load(case)
    return {"case": case, "dossier": d, "decisions": decisions.latest(records),
            "blockers": decisions.merge_blockers(d, records), "measured": decisions.measured(d, records)}


def who_decides(d, records, item, decision):
    """(owner, evidence) for a valid decision, or None. Who decides comes from the dossier, never the page."""
    refusal = next((r for r in d["refusals"] if r["id"] == item), None)
    unit = next((u for u in d["units"] if u["id"] == item), None)
    approver = d["owners"]["approver"]
    if refusal and (decision in refusal["options"] or decision == "reopen"):
        return refusal["owner"], refusal["evidence"]
    if unit and unit["status"] == "held" and decision in ("accepted without proof", "reopen"):
        return approver, [unit["id"]]                       # the approver takes the missing proof on themselves
    if item == "MERGE" and decision == "approved" and not decisions.merge_blockers(d, records):
        return approver, [d["id"]]
    if item == "MERGE" and decision in ("changes requested", "reopen"):
        return approver, [d["id"]]
    return None


def decide(case, item, decision, note=""):
    d, records = dossier(case), decisions.load(case)
    found = who_decides(d, records, item, decision)
    if not found:
        raise ValueError(f"not a valid decision: {item} / {decision}")
    decisions.record(case, d["id"], item, decision, found[0], found[1], note)


class Handler(BaseHTTPRequestHandler):
    def send(self, body, kind, code=200):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value):
        self.send(json.dumps(value).encode(), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/cases":
            return self.send_json(cases())
        if url.path == "/api/state":
            return self.send_json(state(parse_qs(url.query).get("case", ["2283"])[0]))
        path = (WEB / url.path.lstrip("/")).resolve()
        if url.path == "/" or not path.is_file() or WEB not in path.parents:
            path = WEB / "index.html"
        self.send(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            decide(body["case"], body["item"], body["decision"], body.get("note", ""))
        except (KeyError, ValueError, FileNotFoundError) as e:
            return self.send(str(e).encode(), "text/plain", 400)
        self.send_json(state(body["case"]))

    def log_message(self, *args):
        pass


def main():
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8283
    url = f"http://localhost:{port}"
    print(f"Earned Trust reviewer: {url}  (Ctrl+C to stop)")
    if "--no-open" not in args:
        webbrowser.open(url)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
