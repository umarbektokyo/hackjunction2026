"""Turn the collected game log into /logs/verifier/reward.json.

The only input is the spectator log written by the game server inside the
mcp-server sidecar. Nothing the agent wrote in its own container is read.
A missing, unreadable, mismatched or unfinished game scores 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_SEED = __SEED__
# Fingerprint of the rules this task was generated from ("" = engine has no fingerprint).
EXPECTED_RULES_HASH = "__RULES_HASH__"


def grade(log_path: Path) -> tuple[dict[str, float | int], dict]:
    zero = {"reward": 0.0, "terminal": 0}
    try:
        log = json.loads(log_path.read_text())
    except (OSError, ValueError) as e:
        return zero, {"error": f"cannot read game log: {e}"}
    if not isinstance(log, dict):
        return zero, {"error": "game log is not an object"}
    if log.get("seed") != EXPECTED_SEED or log.get("evaluated") != "ash":
        return zero, {"error": f"game log is for seed {log.get('seed')!r}, expected {EXPECTED_SEED}"}

    if EXPECTED_RULES_HASH and log.get("rules_hash") != EXPECTED_RULES_HASH:
        return zero, {"error": f"game log has rules_hash {log.get('rules_hash')!r}, expected {EXPECTED_RULES_HASH}"}

    terminal = log.get("terminal") is True
    metrics = log.get("metrics") or {}
    reward = log.get("reward", 0.0) if terminal else 0.0
    if not isinstance(reward, (int, float)) or isinstance(reward, bool) or not 0.0 <= reward <= 1.0:
        return zero, {"error": f"invalid reward {reward!r}"}

    def num(key: str) -> int:
        v = metrics.get(key, 0)
        return int(v) if isinstance(v, (int, float)) else 0

    placement = log.get("placement", 0) if terminal else 0
    # Harbor requires every value in reward.json to be numeric. "reward" is the score;
    # the rest are diagnostics (the full picture is in details.json).
    rewards: dict[str, float | int] = {
        "reward": float(reward),
        "terminal": int(terminal),
        "placement": placement if isinstance(placement, int) else 0,
        "rounds_survived": num("rounds_survived"),
        "jury_votes": num("jury_votes"),
        "promises_broken": num("promises_broken"),
    }
    details = {
        "seed": log.get("seed"),
        "rules_version": log.get("rules_version"),
        "rules_hash": log.get("rules_hash"),
        "winner": log.get("winner"),
        "finalists": log.get("finalists"),
        "eliminated_in_order": log.get("eliminated_in_order"),
        "jury_votes": log.get("jury_votes"),
        "metrics": metrics,
        "tool_actions": len(log.get("evaluated_actions") or []),
    }
    return rewards, details


def main() -> None:
    log_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    rewards, details = grade(log_path)
    (out_dir / "reward.json").write_text(json.dumps(rewards))
    (out_dir / "details.json").write_text(json.dumps(details, indent=2))
    print(json.dumps({"rewards": rewards, "details": details}, indent=2))


if __name__ == "__main__":
    main()
