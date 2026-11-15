"""Deterministic NPC opponents.

An NPC only uses information a player in its seat legitimately has:
public events (who is alive, vote tallies, public activity counts), messages visible
to it, requests and promises it is party to, alliances it belongs to, and promise
outcomes revealed to it. It never reads other players' ballots, private messages
addressed to others, or personalities.
NPCs optimize their own survival; there is no special logic for the evaluated player.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import config
from .config import JURY, TRUST, Personality

if TYPE_CHECKING:
    from .game import Alliance, Game, Promise, Request


class NPC:
    def __init__(self, pid: str, p: Personality, game: "Game"):
        self.id = pid
        self.p = p
        self.g = game
        self.trust: dict[str, float] = {}
        for o in game.cfg.players:
            if o != pid:
                noise = (game.rand("trust0", pid, o) * 2 - 1) * TRUST.initial_noise
                self.trust[o] = TRUST.initial + noise
        self.kept_to_me: dict[str, int] = {o: 0 for o in self.trust}
        self.broken_to_me: dict[str, int] = {o: 0 for o in self.trust}
        self.voted_me_out: list[str] = []
        self.ties: dict[str, float] = {o: 0.0 for o in self.trust}
        self._asked: set[tuple[int, str, str]] = set()  # (round, kind, key) already asked
        self._proposed: set[tuple[str, ...]] = set()

    # ------------------------------------------------------------- knowledge
    def _threat(self, t: str) -> float:
        g = self.g
        score = {p: g.round_activity(p) + 0.5 * (g.round_activity(p, g.round - 1) if g.round > 1 else 0)
                 for p in g.alive}
        top = max(score.values()) or 1.0
        return score.get(t, 0.0) / top

    def _my_promises(self) -> list["Promise"]:
        return [pr for pr in self.g.promises.values()
                if pr.promiser == self.id and pr.round == self.g.round and pr.status == "open"]

    def _requests_for(self, t: str) -> int:
        return sum(1 for r in self.g.requests.values()
                   if r.to == self.id and r.round == self.g.round and r.kind == "vote_for" and r.target == t)

    def score(self, t: str) -> float:
        p = self.p
        s = p.threat * config.THREAT_SCALE * self._threat(t)
        if self.g.in_alliance(self.id, t):
            s -= p.loyalty
        s -= p.trust_w * (self.trust[t] - 0.5) * 2
        s += config.OUTSIDER_W / (1 + self.ties[t])
        s += p.retaliation * 0.8 * min(2, self.broken_to_me[t])
        s += p.consensus * 0.4 * self._requests_for(t)
        # Messages influence only players who can actually see them. Structured
        # vote_target avoids making game outcomes depend on text parsing.
        for ev in self.g.events:
            if (ev.type == "message_sent" and ev.round == self.g.round
                    and ev.actor != self.id and ev.data.get("vote_target") == t
                    and self.g.visible(ev, self.id)):
                speaker = ev.actor
                if speaker in self.trust:
                    s += p.consensus * (0.5 + self.trust[speaker])
        for pr in self._my_promises():
            if pr.kind == "vote_for" and pr.target == t:
                s += p.honesty * 2
            if pr.kind == "spare" and pr.target == t:
                s -= p.honesty * 2
        return s

    def preferred_target(self, candidates: list[str] | None = None) -> str:
        cands = [c for c in (candidates or self.g.alive) if c != self.id]
        return max(sorted(cands), key=self.score)

    # --------------------------------------------------------------- actions
    def decide_slot(self) -> dict:
        g = self.g
        if g.rand("slot", g.round, self.id, g.slot_index(self.id)) > self.p.proactivity:
            return {"type": "pass"}
        others = [o for o in g.alive if o != self.id]
        by_trust = sorted(others, key=lambda o: (-self.trust[o], o))

        # 1. Seek an alliance if I have none.
        if not g.active_alliances(self.id):
            pending = any(al.status == "pending" and self.id in al.members for al in g.alliances.values())
            if not pending:
                for o in by_trust[:3]:
                    key = tuple(sorted((self.id, o)))
                    if key not in self._proposed and self.trust[o] >= self.p.accept - 0.05 \
                            and len(g.active_alliances(o)) < g.cfg.max_alliances:
                        self._proposed.add(key)
                        return {"type": "propose_alliance", "members": [o]}

        target = self.preferred_target()
        if not self._sent_message("public"):
            return {"type": "message", "channel": "public",
                    "text": f"I think {target} is the biggest threat this round.",
                    "vote_target": target}
        if not self._sent_message("private"):
            recipient = by_trust[0]
            if recipient != target:
                return {"type": "message", "channel": "private", "to": recipient,
                        "text": f"I trust you. I plan to vote for {target}.",
                        "vote_target": target}

        # 2. Build a majority against my preferred target.
        for o in by_trust:
            if o == target:
                continue
            k = (g.round, "vote_for:" + target, o)
            if k not in self._asked and len([a for a in self._asked if a[0] == g.round]) < 3:
                self._asked.add(k)
                return {"type": "request", "to": o, "kind": "vote_for", "target": target}

        # 3. Ask a trusted player to spare me if I drew votes last time.
        last = [h for h in g.ballot_history if h["round"] == g.round - 1]
        drew = any(t == self.id for h in last for t in h["ballots"].values())
        if drew:
            for o in by_trust:
                k = (g.round, "spare", o)
                if k not in self._asked:
                    self._asked.add(k)
                    return {"type": "request", "to": o, "kind": "spare", "target": self.id}

        # 4. Reassure an ally (only if I actually intend to spare them).
        for al in g.active_alliances(self.id):
            for o in al.members:
                k = (g.round, "offer", o)
                if o != self.id and k not in self._asked and o != target and self.p.honesty >= 0.7:
                    self._asked.add(k)
                    return {"type": "promise", "to": o, "kind": "spare", "target": o}
        return {"type": "pass"}

    def _sent_message(self, channel: str) -> bool:
        return any(ev.type == "message_sent" and ev.actor == self.id
                   and ev.round == self.g.round and ev.data.get("channel") == channel
                   for ev in self.g.events)

    def consider_alliance(self, al: "Alliance") -> bool:
        others = [m for m in al.members if m != self.id]
        if len(self.g.active_alliances(self.id)) >= self.g.cfg.max_alliances:
            return False
        trust = sum(self.trust[o] for o in others) / len(others)
        return trust >= self.p.accept

    def consider_request(self, req: "Request") -> bool:
        p, g = self.p, self.g
        liar = p.honesty < 0.5
        if self.trust[req.frm] < p.accept - (0.1 if req.kind == "spare" else 0.0):
            return False
        if req.kind == "spare":
            # An honest player won't promise to spare the person it most wants out.
            return liar or self.preferred_target() != req.frm
        # vote_for
        if g.in_alliance(self.id, req.target) and p.loyalty > 0.6:
            return False
        if any(pr.kind == "vote_for" and pr.target != req.target for pr in self._my_promises()):
            return liar
        if any(pr.kind == "spare" and pr.target == req.target for pr in self._my_promises()):
            return liar
        ranked = sorted([o for o in g.alive if o != self.id], key=lambda o: (-self.score(o), o))
        return liar or req.target in ranked[:3]

    def decide_vote(self, candidates: list[str], revote: bool = False) -> str:
        cands = sorted(c for c in candidates if c != self.id)
        noise = {c: self.g.rand("vote", self.g.round, revote, self.id, c) * self.p.exploration for c in cands}
        return max(cands, key=lambda c: self.score(c) + noise[c])

    def jury_vote(self, finalists: list[str]) -> str:
        def s(f: str) -> float:
            return (JURY.trust * self.trust[f] + JURY.kept * self.kept_to_me[f]
                    + JURY.broken * self.broken_to_me[f] + JURY.voted_me_out * (f in self.voted_me_out))
        a, b = finalists
        if abs(s(a) - s(b)) < 1e-9:
            return finalists[0] if self.g.rand("jury", self.id) < 0.5 else finalists[1]
        return a if s(a) > s(b) else b

    # ------------------------------------------------------------- callbacks
    def _adjust(self, o: str, d: float) -> None:
        self.trust[o] = min(1.0, max(0.0, self.trust[o] + d))

    def on_answer(self, other: str, accepted: bool) -> None:
        self._adjust(other, TRUST.agreed if accepted else TRUST.declined)
        if accepted:
            self.ties[other] += 1

    def on_offered(self, other: str) -> None:
        self._adjust(other, TRUST.offered)
        self.ties[other] += 0.5

    def on_promise_outcome(self, pr: "Promise") -> None:
        if pr.status == "kept":
            self.kept_to_me[pr.promiser] += 1
            self.ties[pr.promiser] += 1
            self._adjust(pr.promiser, TRUST.promise_kept)
        elif pr.status == "broken":
            self.broken_to_me[pr.promiser] += 1
            self._adjust(pr.promiser, TRUST.promise_broken * (1 + self.p.retaliation))

    def on_eliminated(self, voters: list[str]) -> None:
        self.voted_me_out = list(voters)
