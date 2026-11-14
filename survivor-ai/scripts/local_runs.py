"""Fast development runs without Docker: one local game server per game, Claude Code in
headless mode as the player, many games in parallel. Same engine, same instruction and the
same MCP tools as the Harbor tasks; the official numbers still come from Harbor.

The player gets no built-in tools at all (--tools ""), only the `survivor` MCP server, and runs
in an empty directory with no user/project settings, so it cannot read the engine source.

    nix develop -c uv run python scripts/local_runs.py --model claude-haiku-5-5 --seeds 101-105 --k 3 -j 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_used_ports: set[int] = set()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def wait_port(port: int, timeout: float = 20) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            _, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            return
        except OSError:
            await asyncio.sleep(0.2)
    raise TimeoutError(f"game server on {port} did not start")


async def start_server(seed: int, gdir: Path) -> tuple[asyncio.subprocess.Process, int]:
    """Start this game's server and make sure the port really belongs to it. A port taken by
    another process would silently connect the player to a different game."""
    for _ in range(5):
        port = free_port()
        if port in _used_ports:
            continue
        _used_ports.add(port)
        env = {**os.environ, "SURVIVOR_SEED": str(seed), "SURVIVOR_RESULT": str(gdir / "game.json"),
               "PORT": str(port)}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "survivor.mcp_server", cwd=ROOT, env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=open(gdir / "server.log", "a"))
        try:
            await wait_port(port)
            await asyncio.sleep(1.0)
            if proc.returncode is None:  # still alive: the bind succeeded, the port is ours
                (gdir / "port").write_text(str(port))
                return proc, port
        except TimeoutError:
            pass
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()
    raise RuntimeError("could not start a game server on a free port")


def instruction(seed: int) -> str:
    p = ROOT / "harbor" / "tasks" / f"survivor-seed-{seed}" / "instruction.md"
    if not p.exists():
        p = ROOT / "harbor" / "tasks" / "survivor-seed-101" / "instruction.md"
    return p.read_text()


async def one_game(model: str, seed: int, attempt: int, out: Path, timeout: float, effort: str | None) -> dict:
    gdir = out / f"seed{seed}-a{attempt}"
    gdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    status = "ok"
    server = None
    try:
        server, port = await start_server(seed, gdir)
        with tempfile.TemporaryDirectory() as play_dir:
            cfg = Path(play_dir) / "mcp.json"
            cfg.write_text(json.dumps({"mcpServers": {"survivor": {"type": "http", "url": f"http://127.0.0.1:{port}/mcp"}}}))
            cmd = ["claude", "-p", instruction(seed), "--model", model, "--tools", "",
                   "--strict-mcp-config", "--mcp-config", str(cfg), "--allowedTools", "mcp__survivor",
                   "--setting-sources", "", "--no-session-persistence",
                   "--output-format", "stream-json", "--verbose"]
            if effort:
                cmd += ["--effort", effort]
            player_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_SESSION")}
            player_env.pop("CLAUDECODE", None)
            with open(gdir / "transcript.jsonl", "w") as tr, open(gdir / "player.err", "w") as er:
                proc = await asyncio.create_subprocess_exec(*cmd, cwd=play_dir, stdout=tr, stderr=er, env=player_env)
                try:
                    await asyncio.wait_for(proc.wait(), timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    status = "timeout"
    except Exception as e:  # infrastructure failure: report it, never score it as play
        status = f"infra-error: {e}"
    finally:
        if server is not None:
            if server.returncode is None:
                server.terminate()
            await server.wait()
    log = json.loads((gdir / "game.json").read_text()) if (gdir / "game.json").exists() else {}
    usage = {}
    tr_path = gdir / "transcript.jsonl"
    if tr_path.exists():
        for line in tr_path.read_text().splitlines():
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("type") == "rate_limit_event" and (m.get("rate_limit_info") or {}).get("status") == "rejected":
                status = "infra-rate-limited"  # the player was cut off by usage limits: not play
            if m.get("type") == "result":
                usage = {"cost_usd": m.get("total_cost_usd"), "num_turns": m.get("num_turns"),
                         "result_subtype": m.get("subtype")}
                if m.get("is_error") and status == "ok":
                    status = f"infra-player-error: {str(m.get('result'))[:120]}"
    row = {"model": model, "seed": seed, "attempt": attempt, "status": status,
           "reward": log.get("reward", 0.0), "placement": log.get("placement"), "terminal": log.get("terminal"),
           "seconds": round(time.time() - t0), **usage}
    (gdir / "row.json").write_text(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)
    return row


def parse_seeds(s: str) -> list[int]:
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--seeds", default="101-105")
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("-j", "--parallel", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=2400)
    ap.add_argument("--effort", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out or ROOT / "results" / "runs" / f"local-{a.model}-{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(a.parallel)

    async def guarded(seed: int, att: int) -> dict:
        async with sem:
            return await one_game(a.model, seed, att, out, a.timeout, a.effort)

    rows = await asyncio.gather(*(guarded(s, k) for s in parse_seeds(a.seeds) for k in range(1, a.k + 1)))
    (out / "summary.json").write_text(json.dumps(rows, indent=1))
    ok = [r for r in rows if not r["status"].startswith("infra")]
    if ok:
        mean = sum(r["reward"] for r in ok) / len(ok)
        print(f"{a.model}: {len(ok)} games, mean reward {mean:.3f}, wins {sum(r['placement'] == 1 for r in ok)}, "
              f"notional API cost ${sum(r.get('cost_usd') or 0 for r in ok):.2f} -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
