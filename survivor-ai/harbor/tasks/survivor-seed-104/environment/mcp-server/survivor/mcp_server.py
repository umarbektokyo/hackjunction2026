"""MCP tool boundary for the evaluated player.

One game per server process. Every tool acts as the evaluated player; there is no
argument that selects a different player, no reset, and no access to hidden state.
After every accepted action the full spectator log is written to SURVIVOR_RESULT
(inside this container only); Harbor's collect hook snapshots it for the verifier.

    SURVIVOR_SEED=7 python -m survivor.mcp_server
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .config import GameConfig
from .game import ActionError, Game

SEED = int(os.environ.get("SURVIVOR_SEED", "0"))
RESULT = Path(os.environ.get("SURVIVOR_RESULT", "/results/game.json"))

game = Game(GameConfig(seed=SEED))
lock = threading.Lock()
cursor = {"seq": 0}

server = MCPServer(
    "survivor",
    instructions="You are player 'ash' in an 8-player elimination game. Call get_state first.",
)


def _save() -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    tmp = RESULT.with_suffix(".tmp")
    tmp.write_text(json.dumps(game.export()))
    tmp.replace(RESULT)


def _state() -> dict[str, Any]:
    obs = game.observe(since=cursor["seq"])
    cursor["seq"] = obs["last_seq"]
    return obs


def _act(action: dict[str, Any]) -> dict[str, Any]:
    with lock:
        try:
            result = game.act(action)
        except (ActionError, KeyError, TypeError) as e:
            return {"ok": False, "error": str(e), "state": _state()}
        _save()
        return {**result, "state": _state()}


@server.tool()
def get_state() -> dict[str, Any]:
    """Your current view of the game: phase, whether it is your turn, alliances,
    items waiting for your answer, this round's promises, and events you have not seen yet."""
    with lock:
        return _state()


@server.tool()
def get_history(round: int | None = None) -> list[dict[str, Any]]:
    """Every event visible to you (optionally only one round)."""
    with lock:
        events = game.observe(since=0)["events"]
    return [e for e in events if round is None or e["round"] == round]


@server.tool()
def propose_alliance(members: list[str]) -> dict[str, Any]:
    """Uses your slot. Propose an alliance with 1-3 other living players. It becomes active
    only if every member accepts. Alliance members see each other's alliance events."""
    return _act({"type": "propose_alliance", "members": members})


@server.tool()
def request_promise(to: str, kind: Literal["spare", "vote_for"], target: str = "") -> dict[str, Any]:
    """Uses your slot. Ask `to` for a promise about their vote this round.
    kind='spare': they promise not to vote for you (target is ignored).
    kind='vote_for': they promise to vote for `target`.
    The answer comes back immediately. Whether they kept it is revealed to you after the vote."""
    return _act({"type": "request", "to": to, "kind": kind, "target": target})


@server.tool()
def offer_promise(to: str, kind: Literal["spare", "vote_for"], target: str = "") -> dict[str, Any]:
    """Uses your slot. Promise `to` something about your own vote this round.
    kind='spare': you will not vote for `to`. kind='vote_for': you will vote for `target`.
    The engine checks it against your ballot and tells `to` whether you kept it."""
    return _act({"type": "promise", "to": to, "kind": kind, "target": target})


@server.tool()
def respond(item_id: str, accept: bool) -> dict[str, Any]:
    """Does not use your slot. Accept or decline an alliance proposal or promise request
    listed under waiting_for_your_answer. Accepting a request creates a promise from you.
    Unanswered items are declined when voting starts."""
    return _act({"type": "respond", "item_id": item_id, "accept": accept})


@server.tool()
def leave_alliance(alliance_id: str) -> dict[str, Any]:
    """Uses your slot. Leave one of your active alliances."""
    return _act({"type": "leave_alliance", "alliance_id": alliance_id})


@server.tool()
def pass_turn() -> dict[str, Any]:
    """Uses your slot without doing anything. If every living player passes in the same
    turn, discussion ends early."""
    return _act({"type": "pass"})


@server.tool()
def vote(target: str) -> dict[str, Any]:
    """Cast your secret ballot during voting (or a revote). Ballots are simultaneous:
    other players have already decided theirs."""
    return _act({"type": "vote", "target": target})


def main() -> None:
    _save()
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host="0.0.0.0",
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
