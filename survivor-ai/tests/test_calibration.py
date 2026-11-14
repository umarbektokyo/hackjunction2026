"""Calibration gates (after StoreBench): honest anchors must be ordered, and every exploit
anchor must score below every honest anchor. If a rule change breaks a gate, rebalance the
game; do not relax the gate."""

import statistics

from survivor.config import GameConfig
from survivor.game import Game
from survivor.policies import AllianceFarmer, Coalition, Exploiter, RandomPolicy, Reference, StopEarly, do_nothing, passive, play

SEEDS = range(300, 420)  # gate seeds, disjoint from tuning (1000+) and reporting (0-199)


def mean_reward(make):
    return statistics.mean(play(Game(GameConfig(seed=s)), make(s)).reward() for s in SEEDS)


def test_calibration_gates():
    r = {
        "do_nothing": mean_reward(lambda s: do_nothing),
        "stop_early": mean_reward(lambda s: StopEarly(1)),
        "random": mean_reward(lambda s: RandomPolicy(s)),
        "passive": mean_reward(lambda s: passive),
        "reference": mean_reward(lambda s: Reference()),
        "coalition": mean_reward(lambda s: Coalition(1, 0)),
        "exploiter": mean_reward(lambda s: Exploiter(s)),
        "alliance_farmer": mean_reward(lambda s: AllianceFarmer()),
    }
    print(r)
    # Doing nothing or stopping early earns nothing.
    assert r["do_nothing"] == 0.0 and r["stop_early"] == 0.0
    # Judgment beats non-judgment by a clear margin.
    for honest in ("reference", "coalition"):
        assert r[honest] >= r["passive"] + 0.08
        assert r[honest] >= r["random"] + 0.1
    # Exploit suppression: every exploit anchor is below every honest anchor.
    for exploit in ("exploiter", "alliance_farmer"):
        for honest in ("passive", "random", "reference", "coalition"):
            assert r[exploit] < r[honest], (exploit, honest)


def test_cheap_search_cannot_reach_reference_level_by_spam():
    """Every-slot request spam (asking all players to spare me, every round) is not a shortcut."""
    def spam(obs):
        if "you_may_vote_for" in obs:
            return {"type": "vote", "target": obs["you_may_vote_for"][0]}
        if obs["waiting_for_your_answer"]:
            return {"type": "respond", "item_id": obs["waiting_for_your_answer"][0]["id"], "accept": False}
        others = [p for p in obs["alive"] if p != obs["you"]]
        return {"type": "request", "to": others[obs["your_slots_left_this_round"] % len(others)],
                "kind": "spare", "target": obs["you"]}
    assert mean_reward(lambda s: spam) < mean_reward(lambda s: Reference())
