"""Local read-only dashboard for live local Survivor games and saved Harbor runs.

Run from any directory with `python survivor-ai/scripts/dashboard.py` and open
http://127.0.0.1:8765. Local game snapshots update after every accepted action.
Harbor keeps its game logs inside an isolated sidecar until collection, so Harbor
games appear here after the trial finishes.
"""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
LOCAL_RUNS = ROOT / "results" / "runs"
HARBOR_JOBS = ROOT / "jobs"
WEB = ROOT / "dashboard"
HOST, PORT = "127.0.0.1", 8765


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def local_runs() -> list[dict]:
    items = []
    if not LOCAL_RUNS.exists():
        return items
    for game_path in LOCAL_RUNS.glob("*/seed*-a*/game.json"):
        game_dir = game_path.parent
        run_dir = game_dir.parent
        game = read_json(game_path)
        meta = read_json(run_dir / "run.json")
        row = read_json(game_dir / "row.json")
        if not game:
            continue
        agent_label = meta.get("ash_label", meta.get("agent_label", meta.get("model", run_dir.name)))
        opponent_label = meta.get("opponent_label")
        title_prefix = f"{agent_label} vs {opponent_label}" if opponent_label else agent_label
        rel = game_path.relative_to(REPO).as_posix()
        items.append({
            "id": rel,
            "title": f"{title_prefix} · seed {game.get('seed', '?')} · {game_dir.name}",
            "source": "Arena" if meta.get("kind") == "command-agent-arena" else "Local",
            "model": title_prefix,
            "effort": meta.get("effort"),
            "seed": game.get("seed"),
            "status": "completed" if row else ("finished game" if game.get("terminal") else "running"),
            "reward": row.get("reward", game.get("reward")) if row or game.get("terminal") else None,
            "updated": game_path.stat().st_mtime,
            "game": game,
        })
    return items


def harbor_runs() -> list[dict]:
    items = []
    if not HARBOR_JOBS.exists():
        return items
    for game_path in HARBOR_JOBS.glob("*/**/artifacts/snapshot/game.json"):
        trial_dir = game_path.parents[2]
        job_dir = trial_dir.parent
        game = read_json(game_path)
        if not game:
            continue
        trial = read_json(trial_dir / "result.json")
        reward = read_json(trial_dir / "verifier" / "reward.json")
        rel = game_path.relative_to(REPO).as_posix()
        items.append({
            "id": rel,
            "title": f"{job_dir.name} · seed {game.get('seed', '?')} · {trial_dir.name}",
            "source": "Harbor",
            "model": trial.get("agent", trial.get("agent_name", job_dir.name)),
            "effort": None,
            "seed": game.get("seed"),
            "status": "completed" if trial else "collected",
            "reward": reward.get("reward", game.get("reward")),
            "updated": game_path.stat().st_mtime,
            "game": game,
        })
    return items


def get_runs() -> list[dict]:
    runs = local_runs() + harbor_runs()
    return sorted(runs, key=lambda x: x["updated"], reverse=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "SurvivorDashboard/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return  # Keep the terminal quiet while the dashboard is open.

    def respond(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/api/runs":
            data = [{k: v for k, v in item.items() if k != "game"} for item in get_runs()]
            self.respond(200, json.dumps(data).encode(), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/game":
            item_id = parse_qs(parsed.query).get("id", [""])[0]
            candidate = (REPO / item_id).resolve()
            allowed_roots = (LOCAL_RUNS.resolve(), HARBOR_JOBS.resolve())
            if not any(candidate.is_relative_to(root) for root in allowed_roots):
                self.respond(400, b'{"error":"invalid game id"}', "application/json")
                return
            if candidate.name != "game.json" or not candidate.is_file():
                self.respond(404, b'{"error":"game snapshot not found"}', "application/json")
                return
            game = read_json(candidate)
            self.respond(200, json.dumps(game).encode(), "application/json; charset=utf-8")
            return

        name = "index.html" if parsed.path in ("/", "") else parsed.path.lstrip("/")
        if "/" in name or name.startswith("."):
            self.respond(404, b"Not found", "text/plain; charset=utf-8")
            return
        path = WEB / name
        if not path.is_file():
            self.respond(404, b"Not found", "text/plain; charset=utf-8")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        charset = "; charset=utf-8" if content_type.startswith(("text/", "application/javascript")) else ""
        self.respond(200, path.read_bytes(), content_type + charset)


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Survivor dashboard: http://{HOST}:{PORT}")
    print(f"Watching local runs in {LOCAL_RUNS}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
