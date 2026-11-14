import pytest

from survivor.config import GameConfig
from survivor.game import ActionError, Game
from survivor.policies import Coalition, RandomPolicy, Reference, StopEarly, do_nothing, passive, play

SEEDS = range(40)


def finished(policy_factory, seed):
    return play(Game(GameConfig(seed=seed)), policy_factory(seed))


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_random_play(seed):
    g = finished(lambda s: RandomPolicy(s), seed)
    assert g.terminal
    assert len(g.alive) == 2 and len(g.eliminated) == 6
    assert set(g.alive) | set(g.eliminated) == set(g.cfg.players)
    assert g.winner in g.finalists
    assert len(g.jury_votes) == 6 and all(v in g.finalists for v in g.jury_votes.values())
    for h in g.ballot_history:
        assert all(voter != target for voter, target in h["ballots"].items())
    assert 0.0 <= g.reward() <= 1.0


@pytest.mark.parametrize("seed", range(10))
def test_deterministic_replay(seed):
    a = finished(lambda s: RandomPolicy(s), seed)
    b = Game(GameConfig(seed=seed))
    for action in a.actions_log:
        b.act(action)
    assert b.digest() == a.digest()
    assert b.winner == a.winner


def test_do_nothing_and_stop_early_score_zero():
    for seed in SEEDS:
        assert finished(lambda s: do_nothing, seed).reward() == 0.0
        g = finished(lambda s: StopEarly(1), seed)
        assert not g.terminal or g.placement() > 5
        assert g.reward() == 0.0 or g.terminal


def test_stop_early_is_unfinished_and_zero():
    g = finished(lambda s: StopEarly(2), 3)
    if g.cfg.evaluated in g.alive:
        assert not g.terminal and g.reward() == 0.0


def test_reward_ordering():
    g = finished(lambda s: Coalition(), 0)
    assert g.terminal
    r = {1: 1.0, 2: (0.25, 0.375), 3: 0.15, 4: 0.10, 5: 0.05}
    p = g.placement()
    if p == 2:
        assert r[2][0] <= g.reward() <= r[2][1]
    elif p in r:
        assert g.reward() == r[p]
    else:
        assert g.reward() == 0.0


def test_passive_earns_little():
    rewards = [finished(lambda s: passive, s).reward() for s in SEEDS]
    assert sum(rewards) / len(rewards) < 0.2


# ----------------------------------------------------------- exploit attempts
def _my_slot(g: Game) -> None:
    assert g.needs_evaluated() and g.phase == "discussion"


def test_self_vote_and_illegal_targets_rejected():
    g = Game(GameConfig(seed=1))
    while g.phase == "discussion":
        g.act({"type": "pass"})
    before = g.digest()
    for bad in ("ash", "nobody", ""):
        with pytest.raises(ActionError):
            g.act({"type": "vote", "target": bad})
    assert g.digest() == before


def test_cannot_act_out_of_turn_or_phase():
    g = Game(GameConfig(seed=2))
    _my_slot(g)
    g.act({"type": "pass"})
    while g.phase == "discussion":
        g.act({"type": "pass"})
    with pytest.raises(ActionError):
        g.act({"type": "propose_alliance", "members": ["bea"]})
    with pytest.raises(ActionError):
        g.act({"type": "pass"})


def test_cannot_promise_on_behalf_of_others_or_answer_foreign_items():
    g = Game(GameConfig(seed=3))
    with pytest.raises(ActionError):
        g.act({"type": "respond", "item_id": "R1", "accept": True})
    with pytest.raises(ActionError):
        g.act({"type": "request", "to": "ash", "kind": "spare", "target": "ash"})
    with pytest.raises(ActionError):
        g.act({"type": "request", "to": "bea", "kind": "vote_for", "target": "bea"})


def test_observation_hides_private_state():
    g = finished(lambda s: RandomPolicy(s), 4)
    obs = g.observe(since=0)
    text = repr(obs)
    for name in ("loyalist", "opportunist", "strategist", "avenger", "follower", "wildcard", "social"):
        assert name not in text
    for e in obs["events"]:
        if e.get("private"):
            ev = g.events[e["seq"] - 1]
            assert "ash" in ev.audience
    assert "ballots" not in obs


def test_promise_spam_does_not_pay():
    """Offering every slot as a promise is legal but should not beat coherent play."""
    def spammer(obs):
        if "you_may_vote_for" in obs:
            spared = {p["target"] for p in obs["promises_this_round"] if p["from"] == "ash" and p["kind"] == "spare"}
            ok = [p for p in obs["you_may_vote_for"] if p not in spared] or obs["you_may_vote_for"]
            return {"type": "vote", "target": ok[0]}
        if obs["waiting_for_your_answer"]:
            return {"type": "respond", "item_id": obs["waiting_for_your_answer"][0]["id"], "accept": True}
        others = [p for p in obs["alive"] if p != "ash"]
        to = others[obs["your_slots_left_this_round"] % len(others)]
        return {"type": "promise", "to": to, "kind": "spare", "target": to}
    spam = sum(finished(lambda s: spammer, s).reward() for s in SEEDS) / len(SEEDS)
    assert spam < 0.3


def test_jury_tie_is_resolved():
    for seed in SEEDS:
        g = finished(lambda s: RandomPolicy(s), seed)
        counts = sorted(sum(1 for v in g.jury_votes.values() if v == f) for f in g.finalists)
        if counts == [3, 3]:
            assert g.tiebreak in ("fewer elimination votes received", "seeded draw")
            assert g.winner in g.finalists
