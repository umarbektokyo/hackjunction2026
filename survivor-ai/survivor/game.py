"""Survivor game engine: the single source of truth.

Flow per round:  DISCUSSION (slot-based) -> VOTING -> [REVOTE] -> elimination
After 6 eliminations the two finalists face a jury of the eliminated players.

The evaluated player is driven from outside (MCP or a Python policy). Every
other player is an NPC that only sees its own observation (see npc.py).
The engine runs NPC slots synchronously and stops whenever it needs input
from the evaluated player.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .config import (DEAL_MAX_CHARS, DEALS_PER_PAIR_PER_ROUND, JURY, MESSAGE_MAX_CHARS,
                     MESSAGES_PER_CHANNEL_PER_ROUND, PERSONALITIES, RULES_VERSION,
                     TRUST, GameConfig)

DISCUSSION, VOTING, REVOTE, FINISHED = "discussion", "voting", "revote", "finished"
PROMISE_KINDS = ("spare", "vote_for")


def rules_hash(cfg: GameConfig) -> str:
    """Fingerprint of everything that defines the game; the verifier rejects results from other rules."""
    from . import config
    blob = json.dumps({
        "version": RULES_VERSION, "cfg": {k: v for k, v in asdict(cfg).items() if k != "seed"},
        "communication": {"messages_per_channel_per_round": MESSAGES_PER_CHANNEL_PER_ROUND,
                           "message_max_chars": MESSAGE_MAX_CHARS, "deal_max_chars": DEAL_MAX_CHARS,
                           "deals_per_pair_per_round": DEALS_PER_PAIR_PER_ROUND},
        "social_model": {"goal_weight": config.NPC_GOAL_WEIGHT,
                         "reservation_slack": config.NPC_RESERVATION_SLACK},
        "personalities": {k: asdict(v) for k, v in PERSONALITIES.items()},
        "trust": asdict(TRUST), "jury": asdict(JURY),
        "threat_scale": config.THREAT_SCALE, "outsider_w": config.OUTSIDER_W,
    }, sort_keys=True, default=list).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


class ActionError(Exception):
    """Illegal action. State is unchanged."""


@dataclass
class Alliance:
    id: str
    proposer: str
    members: list[str]
    accepted: list[str]
    status: str = "pending"  # pending | active | rejected | dissolved
    round: int = 0


@dataclass
class Request:
    """A asks B for a promise. If B accepts, it becomes a Promise from B to A."""

    id: str
    frm: str
    to: str
    kind: str
    target: str
    round: int
    status: str = "pending"  # pending | accepted | declined | expired


@dataclass
class Promise:
    """promiser commits to promisee about their vote this round.
    spare: promiser will not vote for `target` (target == promisee).
    vote_for: promiser will vote for `target`."""

    id: str
    promiser: str
    promisee: str
    kind: str
    target: str
    round: int
    status: str = "open"  # open | kept | broken | void


@dataclass
class Deal:
    """Conditional exchange: each side promises one vote commitment if accepted."""

    id: str
    frm: str
    to: str
    offer_kind: str
    offer_target: str
    ask_kind: str
    ask_target: str
    text: str
    round: int
    status: str = "pending"  # pending | accepted | declined | expired


@dataclass
class Event:
    seq: int
    round: int
    phase: str
    type: str
    actor: str | None
    audience: list[str] | None  # None = public
    data: dict[str, Any] = field(default_factory=dict)


class Game:
    def __init__(self, config: GameConfig | None = None, *, npc_factory: Callable | None = None,
                 snapshot_callback: Callable[["Game"], None] | None = None):
        from .npc import NPC  # local import to avoid a cycle

        self.cfg = config or GameConfig()
        self.snapshot_callback = snapshot_callback
        self._controller_actor: str | None = None
        self.slots_taken: dict[tuple[int, str], int] = {}
        self.round = 1
        self.phase = DISCUSSION
        self.alive: list[str] = list(self.cfg.players)
        self.eliminated: list[str] = []
        self.alliances: dict[str, Alliance] = {}
        self.requests: dict[str, Request] = {}
        self.promises: dict[str, Promise] = {}
        self.deals: dict[str, Deal] = {}
        self.events: list[Event] = []
        self.activity: dict[str, list[int]] = {p: [] for p in self.cfg.players}
        self.ballots: dict[str, str] = {}
        self.ballot_history: list[dict[str, Any]] = []
        self.revote_targets: list[str] = []
        self.revote_voters: list[str] = []
        self.revotes_done = 0
        self.voted_out_by: dict[str, list[str]] = {}
        self.jury_votes: dict[str, str] = {}
        self.finalists: list[str] = []
        self.winner: str | None = None
        self.tiebreak: str | None = None
        self._ids = 0
        self.actions_log: list[dict[str, Any]] = []  # evaluated player's accepted actions, for replay

        names = list(PERSONALITIES)
        self.keyed_rng("personalities").shuffle(names)
        self.personality = dict(zip(self.cfg.npcs, names))
        make_npc = npc_factory or (lambda p, personality, game: NPC(p, personality, game))
        self.npcs = {p: make_npc(p, PERSONALITIES[self.personality[p]], self) for p in self.cfg.npcs}

        self._log("game_started", None, None, players=list(self.cfg.players), you=self.cfg.evaluated)
        self._start_discussion()
        self.run_npcs()

    # ------------------------------------------------------------------ utils
    def rand(self, *key: Any) -> float:
        """Purpose-keyed uniform draw in [0, 1). Each draw depends only on (seed, key), never on how many
        draws came before, so an extra or different action by the agent cannot shift later NPC randomness."""
        h = hashlib.sha256(json.dumps([self.cfg.seed, *key]).encode()).digest()
        return int.from_bytes(h[:8], "big") / 2**64

    def keyed_rng(self, *key: Any) -> random.Random:
        return random.Random(int(self.rand(*key) * 2**53))

    def slot_index(self, actor: str) -> int:
        """How many discussion slots `actor` has had this round (stable regardless of other players' moves)."""
        return self.slots_taken.get((self.round, actor), 0)

    def _id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}{self._ids}"

    def _log(self, type_: str, actor: str | None, audience: list[str] | None, **data: Any) -> Event:
        ev = Event(len(self.events) + 1, self.round, self.phase, type_, actor,
                   sorted(set(audience)) if audience is not None else None, data)
        self.events.append(ev)
        self._notify_snapshot()
        return ev

    def _notify_snapshot(self) -> None:
        if self.snapshot_callback:
            self.snapshot_callback(self)

    def _controller_call(self, pid: str, callback: Callable[[], Any]) -> Any:
        previous = self._controller_actor
        self._controller_actor = pid
        self._notify_snapshot()
        try:
            return callback()
        finally:
            self._controller_actor = previous
            self._notify_snapshot()

    def visible(self, ev: Event, pid: str) -> bool:
        return ev.audience is None or pid in ev.audience

    def is_alive(self, p: str) -> bool:
        return p in self.alive

    def in_alliance(self, a: str, b: str) -> bool:
        return any(al.status == "active" and a in al.members and b in al.members for al in self.alliances.values())

    def active_alliances(self, p: str) -> list[Alliance]:
        return [al for al in self.alliances.values() if al.status == "active" and p in al.members]

    def round_activity(self, p: str, rnd: int | None = None) -> int:
        rnd = self.round if rnd is None else rnd
        acts = self.activity[p]
        return acts[rnd - 1] if len(acts) >= rnd else 0

    def _bump_activity(self, p: str) -> None:
        while len(self.activity[p]) < self.round:
            self.activity[p].append(0)
        self.activity[p][self.round - 1] += 1

    @property
    def terminal(self) -> bool:
        return self.phase == FINISHED

    # ------------------------------------------------------------ discussion
    def _start_discussion(self) -> None:
        self.phase = DISCUSSION
        order = list(self.alive)
        self.keyed_rng("order", self.round).shuffle(order)
        self.slot_queue: list[str] = order * self.cfg.discussion_turns
        self.slot_turn = 0
        self.passed_in_turn: set[str] = set()
        self._log("round_started", None, None, round=self.round, alive=list(self.alive), order=order,
                  turns=self.cfg.discussion_turns)

    @property
    def current_actor(self) -> str | None:
        queue = getattr(self, "slot_queue", [])
        return queue[0] if self.phase == DISCUSSION and queue else None

    def needs_evaluated(self) -> bool:
        """True when the engine is waiting for the evaluated player."""
        me = self.cfg.evaluated
        if self.terminal or me not in self.alive:
            return False
        if self.phase == DISCUSSION:
            if not self.slot_queue:  # discussion over: let me answer anything still waiting for me
                return bool(self.pending_for(me))
            return self.current_actor == me
        if self.phase == VOTING:
            return me not in self.ballots
        if self.phase == REVOTE:
            return me in self.revote_voters and me not in self.ballots
        return False

    def pending_for(self, pid: str) -> list[str]:
        return [r.id for r in self.requests.values() if r.to == pid and r.status == "pending"] + \
               [d.id for d in self.deals.values() if d.to == pid and d.status == "pending"] + \
               [a.id for a in self.alliances.values()
                if a.status == "pending" and pid in a.members and pid not in a.accepted]

    def run_npcs(self) -> None:
        """Advance the game until the evaluated player must act or the game ends."""
        guard = 0
        while not self.terminal and not self.needs_evaluated():
            guard += 1
            if guard > 10_000:
                raise RuntimeError("engine did not converge")
            if self.phase == DISCUSSION:
                if not self.slot_queue:
                    self._start_voting()
                    continue
                actor = self.slot_queue[0]
                self._controller_actor = actor
                self._notify_snapshot()
                action = self.npcs[actor].decide_slot()
                self._controller_actor = None
                try:
                    self._apply_slot(actor, action)
                except (ActionError, KeyError, TypeError) as error:
                    self._log("agent_action_rejected", actor, [actor],
                              error=str(error)[:240], fallback="pass")
                    self._apply_slot(actor, {"type": "pass"})
            elif self.phase in (VOTING, REVOTE):
                self._resolve_votes()
        self._controller_actor = self.cfg.evaluated if self.needs_evaluated() else None
        self._notify_snapshot()

    def _consume_slot(self, actor: str, passed: bool) -> None:
        self.slot_queue.pop(0)
        self.slots_taken[(self.round, actor)] = self.slot_index(actor) + 1
        n_alive = len(self.alive)
        self.slot_turn += 1
        if passed:
            self.passed_in_turn.add(actor)
        if self.slot_turn % n_alive == 0:  # a full turn finished
            if len(self.passed_in_turn) == n_alive:  # everyone passed: end discussion early
                self.slot_queue.clear()
                self._log("discussion_ended_early", None, None)
            self.passed_in_turn = set()
        self._notify_snapshot()

    def _apply_slot(self, actor: str, action: dict[str, Any]) -> dict[str, Any]:
        kind = action.get("type")
        result: dict[str, Any] = {"ok": True}
        if kind == "pass":
            self._log("passed", actor, None)
            self._consume_slot(actor, passed=True)
            return result
        if kind == "propose_alliance":
            result = self._propose_alliance(actor, list(action["members"]))
        elif kind == "request":
            result = self._request(actor, action["to"], action["kind"], action["target"])
        elif kind == "promise":
            result = self._promise(actor, action["to"], action["kind"], action["target"])
        elif kind == "message":
            result = self._send_message(actor, action)
        elif kind == "propose_deal":
            result = self._propose_deal(actor, action)
        elif kind == "leave_alliance":
            result = self._leave_alliance(actor, action["alliance_id"])
        else:
            raise ActionError(f"unknown action {kind!r}")
        self._bump_activity(actor)
        self._consume_slot(actor, passed=False)
        return result

    def _check_target(self, actor: str, target: str, allow_self: bool = False) -> None:
        if target not in self.alive:
            raise ActionError(f"{target!r} is not a living player")
        if target == actor and not allow_self:
            raise ActionError("target cannot be yourself")

    def _send_message(self, actor: str, action: dict[str, Any]) -> dict[str, Any]:
        channel = action.get("channel")
        if channel not in ("public", "private"):
            raise ActionError("channel must be 'public' or 'private'")
        text = action.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MESSAGE_MAX_CHARS:
            raise ActionError(f"message text must contain 1-{MESSAGE_MAX_CHARS} characters")
        sent = sum(e.type == "message_sent" and e.actor == actor and e.round == self.round
                   and e.data.get("channel") == channel for e in self.events)
        if sent >= MESSAGES_PER_CHANNEL_PER_ROUND:
            raise ActionError(f"you have already sent a {channel} message this round")
        if channel == "public":
            recipient = None
            audience = None
        else:
            recipient = action.get("to")
            if not isinstance(recipient, str):
                raise ActionError("private messages require a living recipient in 'to'")
            self._check_target(actor, recipient)
            audience = [actor, recipient]
        self._log("message_sent", actor, audience, channel=channel, to=recipient,
                  text=text.strip())
        return {"ok": True, "channel": channel, "to": recipient}

    def _propose_deal(self, actor: str, action: dict[str, Any]) -> dict[str, Any]:
        to = action["to"]
        self._check_target(actor, to)
        offers_this_pair = sum(d.frm == actor and d.to == to and d.round == self.round
                               for d in self.deals.values())
        if offers_this_pair >= DEALS_PER_PAIR_PER_ROUND:
            raise ActionError("you have already proposed a deal to this player this round")
        offer_kind, offer_target = action["offer_kind"], action["offer_target"]
        ask_kind, ask_target = action["ask_kind"], action["ask_target"]
        if offer_kind not in PROMISE_KINDS or ask_kind not in PROMISE_KINDS:
            raise ActionError(f"deal kinds must be one of {PROMISE_KINDS}")
        self._check_target(actor, offer_target)
        self._check_target(to, ask_target)
        if offer_kind == "vote_for" and offer_target == actor:
            raise ActionError("you cannot promise to vote for yourself")
        if offer_kind == "spare" and offer_target != to:
            raise ActionError("a spare offer must promise not to vote for the recipient")
        if ask_kind == "vote_for" and ask_target == to:
            raise ActionError("a player cannot promise to vote for themselves")
        if ask_kind == "spare" and ask_target != actor:
            raise ActionError("a spare request must ask the recipient not to vote for you")
        text = action.get("text", "")
        if not isinstance(text, str) or len(text) > DEAL_MAX_CHARS:
            raise ActionError(f"deal text must be at most {DEAL_MAX_CHARS} characters")
        deal = Deal(self._id("D"), actor, to, offer_kind, offer_target,
                    ask_kind, ask_target, text.strip(), self.round)
        self.deals[deal.id] = deal
        self._log("deal_proposed", actor, [actor, to], deal=deal.id, to=to,
                  offer_kind=offer_kind, offer_target=offer_target,
                  ask_kind=ask_kind, ask_target=ask_target, text=deal.text)
        if to == self.cfg.evaluated:
            return {"ok": True, "deal": deal.id, "status": "pending"}
        accepted = self._controller_call(to, lambda: self.npcs[to].consider_deal(deal))
        self._answer_deal(deal, accepted)
        return {"ok": True, "deal": deal.id, "status": deal.status}

    def _answer_deal(self, deal: Deal, accepted: bool) -> None:
        deal.status = "accepted" if accepted else "declined"
        self._log("deal_" + deal.status, deal.to, [deal.frm, deal.to], deal=deal.id,
                  frm=deal.frm, offer_kind=deal.offer_kind, offer_target=deal.offer_target,
                  ask_kind=deal.ask_kind, ask_target=deal.ask_target)
        for pid, other in ((deal.frm, deal.to), (deal.to, deal.frm)):
            if pid in self.npcs:
                self.npcs[pid].on_answer(other, accepted)
        if accepted:
            self._make_promise(deal.frm, deal.to, deal.offer_kind, deal.offer_target, via=deal.id)
            self._make_promise(deal.to, deal.frm, deal.ask_kind, deal.ask_target, via=deal.id)

    def _propose_alliance(self, actor: str, members: list[str]) -> dict[str, Any]:
        others = sorted(set(m for m in members if m != actor))
        if not 1 <= len(others) <= 3:
            raise ActionError("an alliance needs 1-3 other living players")
        for m in others:
            self._check_target(actor, m)
        if len(self.active_alliances(actor)) >= self.cfg.max_alliances:
            raise ActionError(f"you are already in {self.cfg.max_alliances} alliances; leave one first")
        al = Alliance(self._id("A"), actor, sorted([actor, *others]), [actor], round=self.round)
        self.alliances[al.id] = al
        self._log("alliance_proposed", actor, al.members, alliance=al.id, members=al.members)
        responses = {}
        for m in others:
            if m == self.cfg.evaluated:
                responses[m] = "pending"  # the evaluated player answers with respond()
                continue
            ok = self._controller_call(m, lambda: self.npcs[m].consider_alliance(al))
            responses[m] = "accepted" if ok else "declined"
            if ok:
                al.accepted.append(m)
            else:
                al.status = "rejected"
        self._settle_alliance(al)
        return {"ok": True, "alliance": al.id, "responses": responses, "status": al.status}

    def _settle_alliance(self, al: Alliance) -> None:
        if al.status == "rejected":
            self._log("alliance_rejected", None, al.members, alliance=al.id, accepted=sorted(al.accepted))
            for m in al.members:
                if m != al.proposer and m in self.npcs and m not in al.accepted:
                    pass
            if al.proposer in self.npcs:
                for m in al.members:
                    if m != al.proposer:
                        self.npcs[al.proposer].on_answer(m, m in al.accepted)
            return
        if set(al.accepted) == set(al.members):
            over = [m for m in al.members if len(self.active_alliances(m)) >= self.cfg.max_alliances]
            if over:
                al.status = "rejected"
                self._log("alliance_rejected", None, al.members, alliance=al.id, reason="member at alliance limit",
                          accepted=sorted(al.accepted))
                return
            al.status = "active"
            self._log("alliance_formed", None, al.members, alliance=al.id, members=al.members)
            for m in al.members:
                if m in self.npcs:
                    for o in al.members:
                        if o != m:
                            self.npcs[m].on_answer(o, True)

    def _request(self, actor: str, to: str, kind: str, target: str) -> dict[str, Any]:
        if kind not in PROMISE_KINDS:
            raise ActionError(f"kind must be one of {PROMISE_KINDS}")
        self._check_target(actor, to)
        if kind == "spare":
            target = actor  # "please don't vote for me"
        else:
            self._check_target(to, target)  # can't ask someone to vote for themselves
        req = Request(self._id("R"), actor, to, kind, target, self.round)
        self.requests[req.id] = req
        self._log("request_made", actor, [actor, to], request=req.id, to=to, kind=kind, target=target)
        if to == self.cfg.evaluated:
            return {"ok": True, "request": req.id, "status": "pending"}
        ok = self._controller_call(to, lambda: self.npcs[to].consider_request(req))
        self._answer_request(req, ok)
        return {"ok": True, "request": req.id, "status": req.status,
                **({"promise": self._last_promise_id} if ok else {})}

    def _answer_request(self, req: Request, ok: bool) -> None:
        req.status = "accepted" if ok else "declined"
        self._log("request_" + req.status, req.to, [req.frm, req.to], request=req.id, frm=req.frm,
                  kind=req.kind, target=req.target)
        if ok:
            self._make_promise(req.to, req.frm, req.kind, req.target, via=req.id)
        if req.frm in self.npcs:
            self.npcs[req.frm].on_answer(req.to, ok)

    def _promise(self, actor: str, to: str, kind: str, target: str) -> dict[str, Any]:
        if kind not in PROMISE_KINDS:
            raise ActionError(f"kind must be one of {PROMISE_KINDS}")
        self._check_target(actor, to)
        if kind == "spare":
            target = to
        else:
            self._check_target(actor, target)
        pid = self._make_promise(actor, to, kind, target, via=None)
        if to in self.npcs:
            self.npcs[to].on_offered(actor)
        return {"ok": True, "promise": pid}

    def _make_promise(self, promiser: str, promisee: str, kind: str, target: str, via: str | None) -> str:
        pr = Promise(self._id("P"), promiser, promisee, kind, target, self.round)
        self.promises[pr.id] = pr
        self._last_promise_id = pr.id
        self._log("promise_made", promiser, [promiser, promisee], promise=pr.id, promisee=promisee,
                  kind=kind, target=target, via=via)
        return pr.id

    def _leave_alliance(self, actor: str, aid: str) -> dict[str, Any]:
        al = self.alliances.get(aid)
        if not al or al.status != "active" or actor not in al.members:
            raise ActionError(f"you are not in active alliance {aid!r}")
        al.members = [m for m in al.members if m != actor]
        self._log("alliance_left", actor, [*al.members, actor], alliance=aid)
        if len(al.members) < 2:
            al.status = "dissolved"
            self._log("alliance_dissolved", None, [*al.members, actor], alliance=aid)
        return {"ok": True}

    # ------------------------------------------------- evaluated player API
    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        """Apply one action of the evaluated player, then run NPCs until it is needed again."""
        me = self.cfg.evaluated
        if self.terminal:
            raise ActionError("the game is over")
        if me not in self.alive:
            raise ActionError("you have been eliminated")
        kind = action.get("type")
        if kind == "respond":
            result = self._respond(me, action["item_id"], bool(action["accept"]))
        elif kind == "vote":
            result = self._cast_vote(me, action["target"])
        elif kind in ("propose_alliance", "request", "promise", "message", "propose_deal",
                      "leave_alliance", "pass"):
            if self.phase != DISCUSSION:
                raise ActionError(f"{kind} is only allowed during discussion (phase is {self.phase})")
            if not self.slot_queue and kind == "pass":
                # Discussion is over and I was answering late items: done; the rest are declined.
                self._start_voting()
                result = {"ok": True}
            elif self.current_actor != me:
                raise ActionError("it is not your slot" if self.slot_queue else
                                  "discussion is over; answer waiting items with respond or call pass_turn to start voting")
            else:
                result = self._apply_slot(me, action)
        else:
            raise ActionError(f"unknown action {kind!r}")
        self.actions_log.append(action)
        self.run_npcs()
        return result

    def _respond(self, me: str, item_id: str, accept: bool) -> dict[str, Any]:
        if self.phase != DISCUSSION:
            raise ActionError("responses are only possible during discussion")
        if item_id in self.requests:
            req = self.requests[item_id]
            if req.to != me or req.status != "pending":
                raise ActionError(f"request {item_id} is not waiting for your answer")
            if accept and req.kind == "vote_for" and not self.is_alive(req.target):
                raise ActionError("target is no longer alive")
            self._answer_request(req, accept)
            return {"ok": True, "request": item_id, "status": req.status}
        if item_id in self.deals:
            deal = self.deals[item_id]
            if deal.to != me or deal.status != "pending":
                raise ActionError(f"deal {item_id} is not waiting for your answer")
            self._answer_deal(deal, accept)
            return {"ok": True, "deal": item_id, "status": deal.status}
        if item_id in self.alliances:
            al = self.alliances[item_id]
            if me not in al.members or al.status != "pending" or me in al.accepted:
                raise ActionError(f"alliance {item_id} is not waiting for your answer")
            if accept:
                if len(self.active_alliances(me)) >= self.cfg.max_alliances:
                    raise ActionError("you are at the alliance limit; leave one first")
                al.accepted.append(me)
            else:
                al.status = "rejected"
            self._log("alliance_answered", me, al.members, alliance=al.id, accept=accept)
            self._settle_alliance(al)
            return {"ok": True, "alliance": al.id, "status": al.status}
        raise ActionError(f"unknown item {item_id!r}")

    # ---------------------------------------------------------------- voting
    def _expire_pending(self) -> None:
        for req in self.requests.values():
            if req.status == "pending":
                req.status = "expired"
                self._log("request_expired", None, [req.frm, req.to], request=req.id)
                if req.frm in self.npcs:
                    self.npcs[req.frm].on_answer(req.to, False)
        for deal in self.deals.values():
            if deal.status == "pending":
                deal.status = "expired"
                self._log("deal_expired", None, [deal.frm, deal.to], deal=deal.id)
                for pid, other in ((deal.frm, deal.to), (deal.to, deal.frm)):
                    if pid in self.npcs:
                        self.npcs[pid].on_answer(other, False)
        for al in self.alliances.values():
            if al.status == "pending":
                al.status = "rejected"
                self._log("alliance_rejected", None, al.members, alliance=al.id, reason="not answered in time")

    def _start_voting(self) -> None:
        self._expire_pending()
        self.phase = VOTING
        self.ballots = {}
        self._log("voting_started", None, None, eligible=list(self.alive))
        # NPC ballots are fixed now, before seeing the evaluated player's ballot (simultaneous voting).
        for p in self.alive:
            if p in self.npcs:
                self._controller_actor = p
                self._notify_snapshot()
                self.ballots[p] = self.npcs[p].decide_vote(list(self.alive))
        self._controller_actor = None
        self._notify_snapshot()

    def _cast_vote(self, me: str, target: str) -> dict[str, Any]:
        if self.phase == VOTING:
            allowed = [p for p in self.alive if p != me]
        elif self.phase == REVOTE:
            if me not in self.revote_voters:
                raise ActionError("you are not voting in this revote")
            allowed = list(self.revote_targets)
        else:
            raise ActionError(f"voting is not open (phase is {self.phase})")
        if me in self.ballots:
            raise ActionError("you already voted")
        if target not in allowed:
            raise ActionError(f"you may vote for one of {allowed}")
        self.ballots[me] = target
        return {"ok": True, "voted": target}

    def _resolve_votes(self) -> None:
        tally: dict[str, int] = {}
        for t in self.ballots.values():
            tally[t] = tally.get(t, 0) + 1
        top = max(tally.values())
        leaders = sorted(t for t, n in tally.items() if n == top)
        is_revote = self.phase == REVOTE
        self.ballot_history.append({"round": self.round, "revote": is_revote, "ballots": dict(self.ballots)})
        self._log("votes_tallied", None, None, tally=dict(sorted(tally.items())), revote=is_revote)
        if self.phase == VOTING:
            self._settle_promises()
        if len(leaders) == 1:
            out = leaders[0]
        elif self.revotes_done < self.cfg.max_revotes:
            self.revotes_done += 1
            self.phase = REVOTE
            self.revote_targets = leaders
            self.revote_voters = [p for p in self.alive if p not in leaders]
            self.ballots = {}
            self._log("revote_started", None, None, tied=leaders, voters=self.revote_voters)
            for p in self.revote_voters:
                if p in self.npcs:
                    self._controller_actor = p
                    self._notify_snapshot()
                    self.ballots[p] = self.npcs[p].decide_vote(leaders, revote=True)
            self._controller_actor = None
            self._notify_snapshot()
            if not self.revote_voters:
                self._eliminate(self._tiebreak(leaders), {})
            return
        else:
            out = self._tiebreak(leaders)
        self._eliminate(out, self.ballots)

    def _tiebreak(self, tied: list[str]) -> str:
        """Fewest total votes received earlier in the game survives... i.e. the most-voted goes; then seeded."""
        def past_votes(p: str) -> int:
            return sum(1 for h in self.ballot_history for t in h["ballots"].values() if t == p)
        worst = max(past_votes(p) for p in tied)
        cands = sorted(p for p in tied if past_votes(p) == worst)
        out = cands[0] if len(cands) == 1 else self.keyed_rng("tiebreak", self.round).choice(cands)
        self._log("tiebreak", None, None, tied=tied, eliminated=out,
                  rule="most votes received over the game; seeded draw if still tied")
        return out

    def _settle_promises(self) -> None:
        for pr in self.promises.values():
            if pr.round != self.round or pr.status != "open":
                continue
            ballot = self.ballots.get(pr.promiser)
            if ballot is None or (pr.kind == "vote_for" and pr.target not in self.alive):
                pr.status = "void"
                continue
            kept = ballot != pr.target if pr.kind == "spare" else ballot == pr.target
            pr.status = "kept" if kept else "broken"
            self._log("promise_" + pr.status, pr.promiser, [pr.promiser, pr.promisee], promise=pr.id,
                      promisee=pr.promisee, kind=pr.kind, target=pr.target)
            if pr.promisee in self.npcs:
                self.npcs[pr.promisee].on_promise_outcome(pr)

    def _eliminate(self, out: str, ballots: dict[str, str]) -> None:
        voters = sorted(v for v, t in ballots.items() if t == out)
        self.voted_out_by[out] = voters
        self.alive.remove(out)
        self.eliminated.append(out)
        self._log("eliminated", None, None, player=out, round=self.round)
        self._log("your_voters_revealed", None, [out], voters=voters)
        for al in self.alliances.values():
            if al.status == "active" and out in al.members:
                al.members = [m for m in al.members if m != out]
                if len(al.members) < 2:
                    al.status = "dissolved"
                    self._log("alliance_dissolved", None, [*al.members, out], alliance=al.id)
        if out in self.npcs:
            self.npcs[out].on_eliminated(voters)
        self.revotes_done = 0
        self.revote_targets, self.revote_voters = [], []
        if len(self.alive) == 2:
            self._final()
            return
        if self.cfg.evaluated not in self.alive and not self._fast_forward_ok():
            return
        self.round += 1
        self._start_discussion()

    def _fast_forward_ok(self) -> bool:
        return True  # NPCs keep playing; the evaluated player is now only a juror

    # ----------------------------------------------------------------- final
    def _final(self) -> None:
        self.finalists = sorted(self.alive)
        self.phase = "jury"
        self._log("final", None, None, finalists=self.finalists, jury=list(self.eliminated))
        for j in self.eliminated:
            if j in self.npcs:
                self.jury_votes[j] = self.npcs[j].jury_vote(self.finalists)
            else:
                # An eliminated evaluated player gets no reward either way; it votes by a fixed rule.
                self.jury_votes[j] = self.finalists[0]
        count = {f: sum(1 for v in self.jury_votes.values() if v == f) for f in self.finalists}
        a, b = self.finalists
        if count[a] != count[b]:
            self.winner = a if count[a] > count[b] else b
        else:
            # Tie: the finalist who received fewer elimination votes over the game wins; then seeded.
            def received(p: str) -> int:
                return sum(1 for h in self.ballot_history for t in h["ballots"].values() if t == p)
            if received(a) != received(b):
                self.winner = a if received(a) < received(b) else b
                self.tiebreak = "fewer elimination votes received"
            else:
                self.winner = self.keyed_rng("final-tiebreak").choice(self.finalists)
                self.tiebreak = "seeded draw"
        self._log("jury_voted", None, None, votes=dict(sorted(self.jury_votes.items())), count=count,
                  winner=self.winner, tiebreak=self.tiebreak)
        self.phase = FINISHED

    # ---------------------------------------------------------------- reward
    def reward(self, pid: str | None = None) -> float:
        pid = pid or self.cfg.evaluated
        if not self.terminal:
            return 0.0
        if self.winner == pid:
            return 1.0
        if pid in self.finalists:
            votes = sum(1 for v in self.jury_votes.values() if v == pid)
            return round(self.cfg.finalist_base + self.cfg.finalist_share * votes / max(1, len(self.jury_votes)), 4)
        return dict(self.cfg.placement_reward).get(self.placement(pid), 0.0)

    def placement(self, pid: str | None = None) -> int:
        pid = pid or self.cfg.evaluated
        if self.winner == pid:
            return 1
        if pid in self.finalists:
            return 2
        if pid in self.eliminated:
            return len(self.cfg.players) - self.eliminated.index(pid)
        return 0  # unfinished

    # ----------------------------------------------------------- observation
    def observe(self, pid: str | None = None, since: int = 0) -> dict[str, Any]:
        pid = pid or self.cfg.evaluated
        me_alive = pid in self.alive
        obs: dict[str, Any] = {
            "you": pid,
            "round": self.round,
            "phase": self.phase,
            "your_turn": self.needs_evaluated() if pid == self.cfg.evaluated else False,
            "alive": list(self.alive),
            "eliminated_in_order": list(self.eliminated),
            "activity_this_round": {p: self.round_activity(p) for p in self.alive},
            "activity_last_round": {p: self.round_activity(p, self.round - 1) if self.round > 1 else 0
                                    for p in self.alive},
        }
        if self.phase == DISCUSSION:
            remaining = self.slot_queue.count(pid) if me_alive else 0
            obs["your_slots_left_this_round"] = remaining
            if not self.slot_queue and me_alive:
                obs["note"] = "Discussion is over. Answer waiting items with respond, then pass_turn to start voting."
        obs["your_alliances"] = [
            {"id": al.id, "members": al.members, "status": al.status}
            for al in self.alliances.values() if pid in al.members and al.status in ("active", "pending")
        ]
        obs["waiting_for_your_answer"] = [
            *({"id": r.id, "type": "request", "from": r.frm, "kind": r.kind, "target": r.target}
              for r in self.requests.values() if r.to == pid and r.status == "pending"),
            *({"id": d.id, "type": "deal", "from": d.frm, "offer_kind": d.offer_kind,
               "offer_target": d.offer_target, "ask_kind": d.ask_kind,
               "ask_target": d.ask_target, "text": d.text}
              for d in self.deals.values() if d.to == pid and d.status == "pending"),
            *({"id": al.id, "type": "alliance", "from": al.proposer, "members": al.members}
              for al in self.alliances.values()
              if al.status == "pending" and pid in al.members and pid not in al.accepted),
        ]
        obs["promises_this_round"] = [
            {"id": pr.id, "from": pr.promiser, "to": pr.promisee, "kind": pr.kind, "target": pr.target,
             "status": pr.status}
            for pr in self.promises.values()
            if pr.round == self.round and pid in (pr.promiser, pr.promisee)
        ]
        if self.phase == VOTING and pid in self.alive:
            obs["you_may_vote_for"] = [p for p in self.alive if p != pid]
        if self.phase == REVOTE and pid in self.revote_voters:
            obs["you_may_vote_for"] = list(self.revote_targets)
        if self.terminal:
            obs["finalists"] = self.finalists
            obs["winner"] = self.winner
            obs["your_reward"] = self.reward(pid) if pid == self.cfg.evaluated else None
        obs["events"] = [self.event_view(e) for e in self.events
                         if e.seq > since and self.visible(e, pid) and e.type != "passed"]
        obs["last_seq"] = self.events[-1].seq if self.events else 0
        return obs

    @staticmethod
    def event_view(e: Event) -> dict[str, Any]:
        d = {"seq": e.seq, "round": e.round, "type": e.type}
        if e.actor:
            d["by"] = e.actor
        if e.audience is not None:
            d["private"] = True
        d.update(e.data)
        return d

    # ---------------------------------------------------------------- export
    def export(self) -> dict[str, Any]:
        """Full spectator log (contains hidden information; never shown to the agent)."""
        return {
            "rules_version": RULES_VERSION,
            "rules_hash": rules_hash(self.cfg),
            "seed": self.cfg.seed,
            "evaluated": self.cfg.evaluated,
            "round": self.round,
            "phase": self.phase,
            "alive": list(self.alive),
            "current_actor": self._controller_actor or self.current_actor,
            "personalities": self.personality,
            "terminal": self.terminal,
            "winner": self.winner,
            "finalists": self.finalists,
            "eliminated_in_order": self.eliminated,
            "jury_votes": self.jury_votes,
            "reward": self.reward(),
            "placement": self.placement(),
            "ballots": self.ballot_history,
            "promises": [asdict(p) for p in self.promises.values()],
            "deals": [asdict(d) for d in self.deals.values()],
            "opponent_controllers": {pid: type(npc).__name__ for pid, npc in self.npcs.items()},
            "npc_private_state": {pid: {
                key: (dict(value) if isinstance(value, dict) else value)
                for key in ("goal", "reservation_slack", "trust", "ties", "kept_to_me", "broken_to_me")
                if (value := getattr(npc, key, None)) is not None
            } for pid, npc in self.npcs.items()},
            "evaluated_private_state": {
                key: getattr(self.evaluated_controller, key)
                for key in ("goal", "reservation_slack")
                if getattr(getattr(self, "evaluated_controller", None), key, None) is not None
            },
            "alliances": [asdict(a) for a in self.alliances.values()],
            "events": [asdict(e) for e in self.events],
            "evaluated_actions": self.actions_log,
            "metrics": self.metrics(),
        }

    def metrics(self, pid: str | None = None) -> dict[str, Any]:
        pid = pid or self.cfg.evaluated
        mine = [p for p in self.promises.values() if p.promiser == pid]
        to_me = [p for p in self.promises.values() if p.promisee == pid]
        deals_made = [d for d in self.deals.values() if d.frm == pid]
        deals_received = [d for d in self.deals.values() if d.to == pid]
        return {
            "promises_made": len(mine),
            "promises_kept": sum(p.status == "kept" for p in mine),
            "promises_broken": sum(p.status == "broken" for p in mine),
            "promises_to_me_broken": sum(p.status == "broken" for p in to_me),
            "promises_to_me_kept": sum(p.status == "kept" for p in to_me),
            "deals_proposed": len(deals_made),
            "deals_proposed_accepted": sum(d.status == "accepted" for d in deals_made),
            "deals_received": len(deals_received),
            "deals_received_accepted": sum(d.status == "accepted" for d in deals_received),
            "controller_errors": sum(e.type == "controller_error" and e.actor == pid for e in self.events),
            "controller_fallbacks": sum(e.type in ("controller_fallback", "controller_action_rejected",
                                                     "agent_action_rejected") and e.actor == pid
                                        for e in self.events),
            "actions": sum(self.activity[pid]),
            "rounds_survived": (self.eliminated.index(pid) + 1) if pid in self.eliminated else self.round,
            "jurors_i_voted_out": sum(1 for j in self.eliminated if pid in self.voted_out_by.get(j, [])),
            "jury_votes": sum(1 for v in self.jury_votes.values() if v == pid),
        }

    def digest(self) -> str:
        """Hash of the public event stream, for determinism checks."""
        blob = json.dumps([asdict(e) for e in self.events], sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()
