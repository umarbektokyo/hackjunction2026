"""Play a scripted policy against a running Survivor MCP server, through the same tools
the agent uses. This is how the reference run (and the stop-early baseline) are executed.

    python -m survivor.mcp_driver --url http://mcp-server:8000/mcp --policy reference
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mcp.client.client import Client

from .policies import Reference, StopEarly, passive

TOOL_FOR = {
    "propose_alliance": lambda a: ("propose_alliance", {"members": a["members"]}),
    "request": lambda a: ("request_promise", {"to": a["to"], "kind": a["kind"], "target": a.get("target", "")}),
    "promise": lambda a: ("offer_promise", {"to": a["to"], "kind": a["kind"], "target": a.get("target", "")}),
    "respond": lambda a: ("respond", {"item_id": a["item_id"], "accept": a["accept"]}),
    "leave_alliance": lambda a: ("leave_alliance", {"alliance_id": a["alliance_id"]}),
    "pass": lambda a: ("pass_turn", {}),
    "vote": lambda a: ("vote", {"target": a["target"]}),
}


def _payload(res: Any) -> dict[str, Any]:
    if getattr(res, "structured_content", None):
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return json.loads(res.content[0].text)


async def drive(url: str, policy_name: str, max_calls: int = 3000) -> dict[str, Any]:
    policy = {"reference": Reference(), "passive": passive, "stop_early": StopEarly(1)}[policy_name]
    async with Client(url) as c:
        obs = _payload(await c.call_tool("get_state", {}))
        for _ in range(max_calls):
            if obs["phase"] == "finished":
                break
            action = policy(obs)
            if action is None:
                break
            name, args = TOOL_FOR[action["type"]](action)
            res = _payload(await c.call_tool(name, args))
            if not res.get("ok", True):
                fallback = {"type": "vote", "target": res["state"]["you_may_vote_for"][0]} \
                    if "you_may_vote_for" in res["state"] else {"type": "pass"}
                name, args = TOOL_FOR[fallback["type"]](fallback)
                res = _payload(await c.call_tool(name, args))
            obs = res["state"]
        return {"phase": obs["phase"], "winner": obs.get("winner"), "reward": obs.get("your_reward")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    ap.add_argument("--policy", default="reference")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(drive(a.url, a.policy))))


if __name__ == "__main__":
    main()
