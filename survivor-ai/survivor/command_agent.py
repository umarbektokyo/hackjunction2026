"""External, LLM-agnostic seat controller for the optional agent arena.

The configured command receives one JSON request on stdin and must print one JSON
object on stdout. The command is researcher-controlled and runs as a local process.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from typing import Any

from .config import NPC_GOAL_WEIGHT, NPC_RESERVATION_SLACK


def seeded_social_profile(game: Any, pid: str) -> tuple[dict[str, Any], float]:
    others = [other for other in game.cfg.players if other != pid]
    rng = game.keyed_rng("npc-goal", pid)
    goal = {"kind": rng.choice(("remove", "protect")),
            "target": rng.choice(others), "weight": NPC_GOAL_WEIGHT}
    low, high = NPC_RESERVATION_SLACK
    slack = low + (high - low) * game.rand("npc-reservation", pid)
    return goal, slack


class CommandSeat:
    """Adapt a JSON-in/JSON-out process to the Survivor NPC/controller interface."""

    def __init__(self, pid: str, personality: Any, game: Any, command: str | list[str],
                 timeout: float = 60.0, label: str | None = None,
                 goal: dict[str, Any] | None = None, reservation_slack: float | None = None):
        self.id, self.p, self.g = pid, personality, game
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("agent command cannot be empty")
        self.timeout = timeout
        self.label = label or self.command[0]
        seeded_goal, seeded_slack = seeded_social_profile(game, pid)
        self.goal = goal or seeded_goal
        self.reservation_slack = seeded_slack if reservation_slack is None else reservation_slack

    def _call(self, decision: str, **context: Any) -> dict[str, Any] | None:
        response_shapes = {
            "discussion_action": {"action": {"type": "...", "...": "..."}},
            "vote": {"target": "legal player name"},
            "jury_vote": {"finalist": "listed finalist name"},
            "respond_alliance": {"accept": True},
            "respond_promise_request": {"accept": True},
            "respond_deal": {"accept": True},
        }
        request = {
            "protocol": "survivor-agent-v1",
            "seat": self.id,
            "decision": decision,
            "response_shape": response_shapes.get(decision, {}),
            "rules_summary": (
                "You control only this seat. Use only the supplied observation and context. "
                "During discussion, actions use one slot; responses to pending items are free. "
                "Promises apply to this round's first ballot and may be kept or broken. "
                "Deals exchange two vote commitments and create both promises only if accepted. "
                "Votes are secret and a jury chooses the winner after six eliminations."
            ),
            "action_schemas": {
                "pass": {"type": "pass"},
                "propose_alliance": {"type": "propose_alliance", "members": ["living player"]},
                "request": {"type": "request", "to": "living player",
                            "kind": "spare|vote_for", "target": "living player"},
                "promise": {"type": "promise", "to": "living player",
                            "kind": "spare|vote_for", "target": "living player"},
                "message": {"type": "message", "channel": "public|private",
                            "text": "message up to 240 characters", "to": "recipient for private"},
                "propose_deal": {"type": "propose_deal", "to": "living player",
                                 "offer_kind": "spare|vote_for", "offer_target": "player",
                                 "ask_kind": "spare|vote_for", "ask_target": "player",
                                 "text": "optional short rationale"},
                "leave_alliance": {"type": "leave_alliance", "alliance_id": "active alliance id"},
                "respond": {"type": "respond", "item_id": "pending item id", "accept": True},
                "vote": {"type": "vote", "target": "one of context.legal_targets"},
            },
            "observation": self.g.observe(self.id, since=0),
            "private_context": {
                "objective": self.goal,
                "reservation_slack": self.reservation_slack,
                "guidance": (f"You privately want {self.goal['kind']} {self.goal['target']}. "
                             "Pursue this objective while protecting your own survival. "
                             "Use reservation_slack as your willingness to accept a deal "
                             "that is worse than your preferred vote."),
            },
            "context": context,
        }
        try:
            with tempfile.TemporaryDirectory(prefix="survivor-seat-") as workdir:
                proc = subprocess.run(
                    self.command,
                    input=json.dumps(request),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=workdir,
                    env=os.environ.copy(),
                    timeout=self.timeout,
                    check=False,
                )
            if proc.returncode != 0:
                raise RuntimeError("agent command returned a non-zero exit status")
            result = json.loads(proc.stdout)
            if not isinstance(result, dict):
                raise ValueError("agent must print one JSON object")
            return result
        except subprocess.TimeoutExpired:
            message = "agent command timed out"
        except OSError:
            message = "could not launch configured agent command"
        except json.JSONDecodeError:
            message = "agent stdout was not a JSON object"
        except (ValueError, RuntimeError):
            message = "agent command returned an invalid response"
        else:
            message = ""
        if message:
            self.g._log("controller_error", self.id, [self.id], decision=decision,
                        controller=self.label, error=message)
            return None

    def _accept(self, decision: str, **context: Any) -> bool:
        result = self._call(decision, **context)
        return result.get("accept") is True if result else False

    def decide_slot(self) -> dict[str, Any]:
        result = self._call("discussion_action", legal_actions=[
            "propose_alliance", "request", "promise", "message", "propose_deal",
            "leave_alliance", "pass",
        ])
        action = result.get("action") if result else None
        return action if isinstance(action, dict) else {"type": "pass"}

    def consider_alliance(self, alliance: Any) -> bool:
        return self._accept("respond_alliance", proposer=alliance.proposer,
                            members=list(alliance.members))

    def consider_request(self, request: Any) -> bool:
        return self._accept("respond_promise_request", from_player=request.frm,
                            kind=request.kind, target=request.target)

    def consider_deal(self, deal: Any) -> bool:
        return self._accept("respond_deal", from_player=deal.frm,
                            offer_kind=deal.offer_kind, offer_target=deal.offer_target,
                            ask_kind=deal.ask_kind, ask_target=deal.ask_target,
                            text=deal.text)

    def decide_vote(self, candidates: list[str], revote: bool = False) -> str:
        legal = [candidate for candidate in candidates if candidate != self.id]
        result = self._call("vote", legal_targets=legal, revote=revote)
        target = result.get("target") if result else None
        if target in legal:
            return target
        fallback = sorted(legal)[0]
        self.g._log("controller_fallback", self.id, [self.id], decision="vote",
                    fallback_target=fallback)
        return fallback

    def jury_vote(self, finalists: list[str]) -> str:
        result = self._call("jury_vote", finalists=list(finalists))
        choice = result.get("finalist") if result else None
        if choice in finalists:
            return choice
        return sorted(finalists)[0]

    # The complete visible history is supplied on each decision, so this adapter
    # does not keep hidden mutable relationship state between process invocations.
    def on_answer(self, other: str, accepted: bool) -> None:
        pass

    def on_offered(self, other: str) -> None:
        pass

    def on_promise_outcome(self, promise: Any) -> None:
        pass

    def on_eliminated(self, voters: list[str]) -> None:
        pass
