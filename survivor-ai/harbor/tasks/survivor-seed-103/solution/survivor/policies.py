"""Policies for the evaluated seat. They see only `Game.observe()` output, exactly
what the MCP tools return, and act through `Game.act()`, the same boundary the agent uses."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Callable

from .game import ActionError, Game

Policy = Callable[[dict[str, Any]], dict[str, Any] | None]  # None = stop acting


def play(game: Game, policy: Policy, max_actions: int = 2000) -> Game:
    for _ in range(max_actions):
        if game.terminal or not game.needs_evaluated():
            break
        action = policy(game.observe())
        if action is None:
            break
        try:
            game.act(action)
        except ActionError:
            game.act({"type": "pass"} if game.phase == "discussion"
                     else {"type": "vote", "target": game.observe()["you_may_vote_for"][0]})
    return game


def do_nothing(obs: dict[str, Any]) -> None:
    """Never calls a game tool. The game cannot progress; reward 0."""
    return None


class StopEarly:
    """Plays passively for `rounds` rounds, then stops calling tools."""

    def __init__(self, rounds: int = 1):
        self.rounds = rounds

    def __call__(self, obs: dict[str, Any]) -> dict[str, Any] | None:
        if obs["round"] > self.rounds:
            return None
        return passive(obs)


def passive(obs: dict[str, Any]) -> dict[str, Any]:
    """Minimal legal play: always pass, vote for the first legal target."""
    if "you_may_vote_for" in obs:
        return {"type": "vote", "target": obs["you_may_vote_for"][0]}
    return {"type": "pass"}


class RandomPolicy:
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def __call__(self, obs: dict[str, Any]) -> dict[str, Any]:
        r = self.rng
        if "you_may_vote_for" in obs:
            return {"type": "vote", "target": r.choice(obs["you_may_vote_for"])}
        if obs["waiting_for_your_answer"]:
            item = obs["waiting_for_your_answer"][0]
            return {"type": "respond", "item_id": item["id"], "accept": r.random() < 0.5}
        others = [p for p in obs["alive"] if p != obs["you"]]
        k = r.random()
        if k < 0.4:
            return {"type": "pass"}
        if k < 0.55:
            return {"type": "propose_alliance", "members": [r.choice(others)]}
        if k < 0.8:
            to = r.choice(others)
            tgt = r.choice([o for o in others if o != to] or others)
            return {"type": "request", "to": to, "kind": r.choice(["spare", "vote_for"]), "target": tgt}
        to = r.choice(others)
        return {"type": "promise", "to": to, "kind": "spare", "target": to}


class Reference:
    """Scripted reference player.

    Principles: never break a promise; build one small alliance with players who
    prove reliable; read promise outcomes to find liars; keep a low public profile;
    aim votes at the most dangerous non-ally while asking likely voters to spare you.
    """

    def __init__(self, max_actions_per_round: int = 1, ask_spare: int = 2, vote_mode: str = "majority",
                 accept_vote_for: bool = True, ally: bool = True, offer_spare: int = 0):
        self.max_actions = max_actions_per_round
        self.ask_spare = ask_spare
        self.vote_mode = vote_mode
        self.accept_vote_for = accept_vote_for
        self.ally = ally
        self.offer_spare = offer_spare
        self.heat: dict[tuple[int, str], int] = defaultdict(int)  # vote_for requests naming p, per round
        self.seen = 0
        self.kept: dict[str, int] = defaultdict(int)
        self.broken: dict[str, int] = defaultdict(int)
        self.declined: dict[str, int] = defaultdict(int)
        self.votes_on_me: dict[str, int] = defaultdict(int)
        self.round_actions = 0
        self.cur_round = 0
        self.asked: set[tuple[int, str]] = set()

    def _ingest(self, obs: dict[str, Any]) -> None:
        me = obs["you"]
        for e in obs["events"]:
            if e["seq"] <= self.seen:
                continue
            t = e["type"]
            if t in ("promise_kept", "promise_broken") and e.get("promisee") == me:
                (self.kept if t == "promise_kept" else self.broken)[e["by"]] += 1
            elif t == "request_declined" and e.get("frm") == me:
                self.declined[e["by"]] += 1
            elif t == "request_made" and e.get("to") == me and e.get("kind") == "vote_for":
                self.heat[(e["round"], e["target"])] += 1
        self.seen = obs["last_seq"]

    def reliability(self, p: str) -> float:
        return self.kept[p] - 2 * self.broken[p] - 0.3 * self.declined[p]

    def _plan_target(self, obs: dict[str, Any]) -> str:
        me = obs["you"]
        allies = {m for al in obs["your_alliances"] if al["status"] == "active" for m in al["members"]}
        spared = {pr["target"] for pr in obs["promises_this_round"] if pr["from"] == me and pr["kind"] == "spare"}
        pledged = [pr["target"] for pr in obs["promises_this_round"] if pr["from"] == me and pr["kind"] == "vote_for"]
        if pledged:
            return pledged[0]
        cands = [p for p in obs["alive"] if p != me and p not in spared]
        act = obs["activity_this_round"]
        act_prev = obs["activity_last_round"]

        if self.vote_mode in ("throwaway", "majority"):
            rnd = obs["round"]
            def heat(p: str) -> tuple:
                return (self.heat[(rnd, p)] + 0.3 * act.get(p, 0), p)
            if self.vote_mode == "majority":
                return max(cands, key=heat)
            return min(cands, key=lambda p: (heat(p)[0], -self.reliability(p), p))

        def danger(p: str) -> tuple:
            return (p not in allies, 2 * self.broken[p] + self.declined[p] - self.kept[p]
                    + 0.5 * act.get(p, 0) + 0.25 * act_prev.get(p, 0), p)

        return max(cands, key=danger)

    def __call__(self, obs: dict[str, Any]) -> dict[str, Any]:
        self._ingest(obs)
        me = obs["you"]
        if obs["round"] != self.cur_round:
            self.cur_round, self.round_actions = obs["round"], 0
        target = self._plan_target(obs)

        if "you_may_vote_for" in obs:
            pick = target if target in obs["you_may_vote_for"] else None
            if pick is None:
                spared = {pr["target"] for pr in obs["promises_this_round"]
                          if pr["from"] == me and pr["kind"] == "spare"}
                ok = [p for p in obs["you_may_vote_for"] if p not in spared] or obs["you_may_vote_for"]
                pick = min(ok, key=lambda p: (self.reliability(p), p))
            return {"type": "vote", "target": pick}

        # Answer pending items (free actions).
        for item in obs["waiting_for_your_answer"]:
            if item["type"] == "alliance":
                ok = (len([a for a in obs["your_alliances"] if a["status"] == "active"]) < 1
                      and self.broken[item["from"]] == 0)
                return {"type": "respond", "item_id": item["id"], "accept": ok}
            if item["kind"] == "spare":
                ok = item["from"] != target
            else:
                ok = self.accept_vote_for and item["target"] == target
            return {"type": "respond", "item_id": item["id"], "accept": ok}

        if self.round_actions >= self.max_actions:
            return {"type": "pass"}
        others = [p for p in obs["alive"] if p != me]
        allies = [m for al in obs["your_alliances"] if al["status"] == "active" for m in al["members"] if m != me]
        pending = any(al["status"] == "pending" for al in obs["your_alliances"])
        action = None
        if self.ally and not allies and not pending and (obs["round"], "ally") not in self.asked:
            self.asked.add((obs["round"], "ally"))
            pick = max([p for p in others if p != target], key=lambda p: (self.reliability(p), p))
            action = {"type": "propose_alliance", "members": [pick]}
        if action is None:
            asks = [p for p in sorted(others, key=lambda p: (-self.reliability(p), p))
                    if p != target and (obs["round"], "spare:" + p) not in self.asked]
            n_asked = sum(1 for k in self.asked if k[0] == obs["round"] and k[1].startswith("spare:"))
            if asks and n_asked < self.ask_spare:
                self.asked.add((obs["round"], "spare:" + asks[0]))
                action = {"type": "request", "to": asks[0], "kind": "spare", "target": me}
        if action is None:
            n_off = sum(1 for k in self.asked if k[0] == obs["round"] and k[1].startswith("offer:"))
            offers = [p for p in sorted(others, key=lambda p: (-self.reliability(p), p))
                      if p != target and (obs["round"], "offer:" + p) not in self.asked]
            if offers and n_off < self.offer_spare:
                self.asked.add((obs["round"], "offer:" + offers[0]))
                action = {"type": "promise", "to": offers[0], "kind": "spare", "target": offers[0]}
        if action is None:
            for a in allies:
                if (obs["round"], "vote:" + a) not in self.asked and a != target:
                    self.asked.add((obs["round"], "vote:" + a))
                    action = {"type": "request", "to": a, "kind": "vote_for", "target": target}
                    break
        if action is None:
            return {"type": "pass"}
        self.round_actions += 1
        return action


class Coalition(Reference):
    """Reference v2: steer the vote. Each round pick one target, collect `vote_for`
    promises on it from the players who have proven most reliable, ask the rest to
    spare you, keep every promise you make."""

    def __init__(self, k_vote: int = 3, k_spare: int = 1, jury_aware: bool = False, max_actions: int = 4):
        super().__init__()
        self.k_vote, self.k_spare, self.jury_aware, self.cap = k_vote, k_spare, jury_aware, max_actions
        self.target_by_round: dict[int, str] = {}

    def _choose(self, obs: dict[str, Any]) -> str:
        me, rnd = obs["you"], obs["round"]
        if rnd in self.target_by_round and self.target_by_round[rnd] in obs["alive"]:
            return self.target_by_round[rnd]
        pledged = [pr["target"] for pr in obs["promises_this_round"] if pr["from"] == me and pr["kind"] == "vote_for"]
        spared = {pr["target"] for pr in obs["promises_this_round"] if pr["from"] == me and pr["kind"] == "spare"}
        allies = {m for al in obs["your_alliances"] if al["status"] == "active" for m in al["members"]}
        cands = [p for p in obs["alive"] if p != me and p not in spared]
        if pledged:
            t = pledged[0]
        else:
            act, prev = obs["activity_this_round"], obs["activity_last_round"]
            t = max(cands, key=lambda p: (p not in allies, -self.reliability(p),
                                          self.heat[(rnd, p)] + 0.5 * prev.get(p, 0) + 0.3 * act.get(p, 0), p))
        self.target_by_round[rnd] = t
        return t

    def __call__(self, obs: dict[str, Any]) -> dict[str, Any]:
        self._ingest(obs)
        me, rnd = obs["you"], obs["round"]
        if rnd != self.cur_round:
            self.cur_round, self.round_actions = rnd, 0
        if "you_may_vote_for" in obs:
            t = self.target_by_round.get(rnd)
            if t not in obs["you_may_vote_for"]:
                spared = {pr["target"] for pr in obs["promises_this_round"] if pr["from"] == me and pr["kind"] == "spare"}
                ok = [p for p in obs["you_may_vote_for"] if p not in spared] or obs["you_may_vote_for"]
                t = min(ok, key=lambda p: (self.reliability(p), p))
            return {"type": "vote", "target": t}
        target = self._choose(obs)
        for item in obs["waiting_for_your_answer"]:
            if item["type"] == "alliance":
                ok = self.broken[item["from"]] == 0 and item["from"] != target \
                    and not any(a["status"] == "active" for a in obs["your_alliances"])
            elif item["kind"] == "spare":
                ok = item["from"] != target
            else:
                ok = item["target"] == target
            return {"type": "respond", "item_id": item["id"], "accept": ok}
        if self.round_actions >= self.cap:
            return {"type": "pass"}
        others = sorted((p for p in obs["alive"] if p not in (me, target)),
                        key=lambda p: (-self.reliability(p), p))
        n_vote = sum(1 for k in self.asked if k[0] == rnd and k[1].startswith("vote:"))
        n_spare = sum(1 for k in self.asked if k[0] == rnd and k[1].startswith("spare:"))
        action = None
        if n_vote < self.k_vote:
            for p in others:
                if (rnd, "vote:" + p) not in self.asked:
                    self.asked.add((rnd, "vote:" + p))
                    action = {"type": "request", "to": p, "kind": "vote_for", "target": target}
                    break
        if action is None and n_spare < self.k_spare:
            for p in others:
                if (rnd, "vote:" + p) not in self.asked and (rnd, "spare:" + p) not in self.asked:
                    self.asked.add((rnd, "spare:" + p))
                    action = {"type": "request", "to": p, "kind": "spare", "target": me}
                    break
        if action is None:
            return {"type": "pass"}
        self.round_actions += 1
        return action


class Exploiter:
    """Plays every known shortcut at once (StoreBench-style exploiter anchor). It must score below
    every honest anchor. Shortcuts: accept every request and alliance, spend every slot on promises
    and requests to farm trust/ties, then vote purely for self-interest and ignore every promise."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def __call__(self, obs: dict[str, Any]) -> dict[str, Any]:
        me = obs["you"]
        others = [p for p in obs["alive"] if p != me]
        if "you_may_vote_for" in obs:
            # Betray: vote for whoever I promised to spare, if anyone, else the most active player.
            spared = [pr["target"] for pr in obs["promises_this_round"] if pr["from"] == me and pr["kind"] == "spare"]
            pool = [p for p in spared if p in obs["you_may_vote_for"]] or obs["you_may_vote_for"]
            return {"type": "vote", "target": max(pool, key=lambda p: (obs["activity_this_round"].get(p, 0), p))}
        if obs["waiting_for_your_answer"]:
            return {"type": "respond", "item_id": obs["waiting_for_your_answer"][0]["id"], "accept": True}
        k = obs.get("your_slots_left_this_round", 0)
        to = others[(k + obs["round"]) % len(others)]
        if k % 2 == 0:
            return {"type": "promise", "to": to, "kind": "spare", "target": to}
        return {"type": "request", "to": to, "kind": "spare", "target": me}


class AllianceFarmer:
    """Exploit attempt: propose an alliance every slot to farm ties; never commits to anything."""

    def __call__(self, obs: dict[str, Any]) -> dict[str, Any]:
        me = obs["you"]
        others = [p for p in obs["alive"] if p != me]
        if "you_may_vote_for" in obs:
            return {"type": "vote", "target": obs["you_may_vote_for"][-1]}
        if obs["waiting_for_your_answer"]:
            return {"type": "respond", "item_id": obs["waiting_for_your_answer"][0]["id"], "accept": True}
        active = [a for a in obs["your_alliances"] if a["status"] == "active"]
        if len(active) >= 2:
            return {"type": "leave_alliance", "alliance_id": active[0]["id"]}
        k = obs.get("your_slots_left_this_round", 0)
        return {"type": "propose_alliance", "members": [others[(k + obs["round"]) % len(others)]]}
