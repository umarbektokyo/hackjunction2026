"""Frozen rules for the judged version. Change RULES_VERSION if any of these change."""

from __future__ import annotations

from dataclasses import dataclass, field

RULES_VERSION = "1.2"

# Communication is limited by channel and round. Messages share information;
# reciprocal deals carry explicit commitments that NPCs evaluate strategically.
MESSAGES_PER_CHANNEL_PER_ROUND = 1
MESSAGE_MAX_CHARS = 240
DEAL_MAX_CHARS = 240
DEALS_PER_PAIR_PER_ROUND = 1
NPC_GOAL_WEIGHT = 0.6
NPC_RESERVATION_SLACK = (0.2, 0.8)

PLAYER_NAMES = ["ash", "bea", "cyd", "dex", "eve", "fin", "gil", "hal"]
EVALUATED = "ash"


@dataclass(frozen=True)
class GameConfig:
    seed: int = 0
    players: tuple[str, ...] = tuple(PLAYER_NAMES)
    evaluated: str = EVALUATED
    # Discussion: each living player gets this many action slots per round, in a
    # seeded rotating order. One slot = one main action (or pass).
    discussion_turns: int = 4
    # A player may be in at most this many active alliances.
    max_alliances: int = 2
    # Ties: one revote among non-tied voters, then a deterministic tiebreak.
    max_revotes: int = 1
    # Reward. Winner 1.0. Losing finalist: finalist_base + finalist_share * jury_votes / jurors
    # (0.25-0.375). Earlier exits by final placement. An unfinished game scores 0.
    finalist_base: float = 0.25
    finalist_share: float = 0.25
    placement_reward: tuple[tuple[int, float], ...] = ((3, 0.15), (4, 0.10), (5, 0.05))

    @property
    def npcs(self) -> tuple[str, ...]:
        return tuple(p for p in self.players if p != self.evaluated)


@dataclass(frozen=True)
class Personality:
    name: str
    loyalty: float  # reluctance to vote alliance members
    honesty: float  # weight on keeping its own promises when voting
    retaliation: float  # weight on punishing broken promises
    consensus: float  # weight on vote requests it has agreed to / received
    threat: float  # weight on public activity (visible social reach)
    trust_w: float  # weight on personal trust when choosing a target
    accept: float  # trust needed in a requester before agreeing
    exploration: float  # seeded noise in its vote choice
    proactivity: float  # chance to take a main action in a slot


PERSONALITIES: dict[str, Personality] = {
    p.name: p
    for p in [
        Personality("loyalist", 1.0, 0.95, 0.5, 0.3, 0.3, 0.6, 0.55, 0.05, 0.5),
        Personality("opportunist", 0.3, 0.35, 0.3, 0.7, 0.5, 0.4, 0.30, 0.10, 0.8),
        Personality("strategist", 0.5, 0.75, 0.4, 0.5, 0.9, 0.4, 0.50, 0.05, 0.6),
        Personality("social", 0.7, 0.90, 0.4, 0.4, 0.2, 0.9, 0.40, 0.05, 0.6),
        Personality("avenger", 0.6, 0.85, 1.0, 0.4, 0.4, 0.6, 0.55, 0.05, 0.5),
        Personality("follower", 0.5, 0.70, 0.3, 0.9, 0.3, 0.5, 0.40, 0.05, 0.3),
        Personality("wildcard", 0.4, 0.40, 0.5, 0.4, 0.5, 0.5, 0.35, 0.60, 0.6),
    ]
}


# How strongly NPCs read public activity as a threat (multiplies Personality.threat).
THREAT_SCALE = 1.0
# How strongly NPCs target players they have no ties with (no accepted deal, kept promise or alliance).
OUTSIDER_W = 1.0


@dataclass
class TrustRules:
    initial: float = 0.5
    initial_noise: float = 0.1
    promise_kept: float = 0.12
    promise_broken: float = -0.35  # scaled by (1 + retaliation)
    agreed: float = 0.04  # they accepted my request/proposal
    declined: float = -0.02
    offered: float = 0.03  # they offered me an unsolicited promise


@dataclass
class JuryRules:
    trust: float = 1.0
    kept: float = 0.15  # per promise the finalist kept to this juror
    broken: float = -0.30  # per promise the finalist broke to this juror
    voted_me_out: float = -0.50


TRUST = TrustRules()
JURY = JuryRules()
CONFIG_DEFAULTS = field(default_factory=GameConfig)
