# Survivor as Harbor tasks

Five Harbor tasks, `tasks/survivor-seed-101` … `survivor-seed-105`. They are identical
except for the game seed. In each one the agent plays `ash` in an 8-player elimination
game against 7 deterministic NPCs, only through the `survivor` MCP server. The reward
is the game's own score (`Game.reward()`): 1.0 for winning the jury vote, partial
credit for a losing finalist and for late eliminations, and 0 for a game that was not
played to the end. The exact table is in each task's `instruction.md`; it is rendered
from `survivor/config.py` when the tasks are generated.

Tested with Harbor 0.26.0 and the local Docker environment.

## Run locally with Codex

For local games without Docker or an API key, use the Codex CLI runner from `survivor-ai/`.
It uses your existing Codex sign-in and connects Codex to each game's Survivor MCP server.
Codex CLI must be installed and signed in, and the selected model must be available to your
Codex account.

```bash
nix develop -c uv run python scripts/local_runs.py --model gpt-5.6-terra --seeds 101-105 --k 3 -j 15
nix develop -c uv run python scripts/local_runs.py --model gpt-5.6-luna --seeds 101-105 --k 3 -j 15
```

The Codex runner uses an empty working directory, ignores user Codex settings, and runs with a
read-only shell sandbox. The game is played through the configured `survivor` MCP server. These
local runs are for development and comparison; the Harbor verifier remains the official score.

## Run with Harbor

All commands are run from `survivor-ai/`. The tasks are committed and self-contained;
nothing has to be built or generated first. Docker must be running.

```bash
alias harbor='uv tool run --from harbor==0.26.0 harbor'   # or: uv tool install harbor==0.26.0
```

| Role | Command | Expected |
|---|---|---|
| **Reference run** (strong model) | `CODEX_FORCE_AUTH_JSON=1 harbor run -p harbor/tasks -a codex -m openai/gpt-5.6-terra -k 3` | measured mean reward 0.417 |
| **Evaluated agent** (lower effort) | `CODEX_FORCE_AUTH_JSON=1 harbor run -p harbor/tasks -a codex -m openai/gpt-5.6-luna --ak reasoning_effort=low -k 3` | measured mean reward 0.225 |
| Baseline: do nothing | `harbor run -p harbor/tasks -a nop` | 0 on every task |
| Baseline: stop early | `SURVIVOR_POLICY=stop_early harbor run -p harbor/tasks -a oracle` | 0 on every task |
| Pipeline sanity check (scripted policy) | `harbor run -p harbor/tasks -a oracle` | see table below |

`-k 3` runs three attempts per task (15 trials per model). Add `-n 5` to run five
trials at a time, `-i survivor-seed-101` to run a single task, `-o <dir>` to change the
output directory.

The **reference run and the evaluated agent are both Codex**, using Terra and Luna
respectively; the evaluated run also sets Luna's reasoning effort to `low`. In the
recorded 15-trial runs, Terra averaged 0.417 and Luna at low effort averaged 0.225,
with no errored trials. Treat these as observed results, not a guarantee: model
sampling and game seeds affect scores. The standard Luna run (default effort) averaged
0.401 on the same five task seeds, so this comparison demonstrates the effect of the
lower-effort evaluated configuration; it does not establish a general Terra-versus-Luna
ranking. `-a oracle` is not the reference: it runs `solution/solve.sh`, a small scripted
policy that plays through the same MCP tools. It exists to prove the pipeline end to
end (MCP server, result collection, separate verifier) without spending LLM credits,
and its rewards must equal an in-process run of the same policy.

The stop-early baseline plays one round passively through MCP and then stops calling
tools. It uses the oracle agent with `SURVIVOR_POLICY=stop_early`, which
`[solution.env]` in `task.toml` passes to `solve.sh` (`reference` is the default,
`passive` also exists). On NixOS without the docker group, wrap the whole command:
`SURVIVOR_POLICY=stop_early sg docker -c "uv tool run --from harbor==0.26.0 harbor run …"`.

### Codex sign-in

The Codex agent uses the Codex CLI and supports Codex's local `auth.json` login. Sign in to
Codex on the host first, then run Harbor with `CODEX_FORCE_AUTH_JSON=1`; Harbor copies the
host's `~/.codex/auth.json` into the isolated agent container for the trial. No provider API
key is required. If your auth file is elsewhere, set `CODEX_AUTH_JSON_PATH` to its path.

```bash
CODEX_FORCE_AUTH_JSON=1 harbor run -p harbor/tasks -a codex -m openai/gpt-5.6-terra -k 3 --job-name reference
CODEX_FORCE_AUTH_JSON=1 harbor run -p harbor/tasks -a codex -m openai/gpt-5.6-luna --ak reasoning_effort=low -k 3 --job-name agent
```

The recorded 15-trial summaries (`codex-terra`, `codex-luna`, and `codex-luna-low-n8`)
are under `jobs/`. Terra: reward 0.417, mean placement 3.33, zero promises broken,
zero errors. Luna at low effort: reward 0.225, mean placement 4.00, 0.73 promises
broken per trial, zero errors. Luna at default effort scored 0.401, showing that the
gap depends on the evaluated effort setting. The low-effort run used Harbor concurrency
8; the default runs used concurrency 4. Concurrency shortened wall time but is not a
gameplay intervention.

Harbor adds the task's `[[environment.mcp_servers]]` entry to Codex's `config.toml`, so the
agent gets the `survivor` game tools inside the task container. The task container installs
Codex CLI at build time; Harbor detects it and skips the per-trial CLI install.

## Where results land

`jobs/<job-name>/` (override with `-o`):

```
jobs/<job>/result.json                               aggregate: mean reward and metrics
jobs/<job>/<task>__<id>/result.json                  one trial
jobs/<job>/<task>__<id>/verifier/reward.json         {"reward": …, "terminal", "placement",
                                                      "rounds_survived", "jury_votes", "promises_broken"}
jobs/<job>/<task>__<id>/verifier/details.json        winner, finalists, elimination order, jury votes, metrics
jobs/<job>/<task>__<id>/artifacts/snapshot/game.json full spectator log of the game (every event and ballot)
jobs/<job>/<task>__<id>/agent/                       agent logs (codex.txt + trajectory, or oracle.txt)
```

`reward` is the score. The other keys in `reward.json` are diagnostics (Harbor only
accepts numbers there) and are averaged in the job summary next to the reward.
`harbor view jobs` opens the results browser.

## How a task is put together

```
tasks/survivor-seed-<S>/
  task.toml                       MCP server declaration, timeouts, collect hook, artifact
  instruction.md                  the player's brief: complete rules, scoring, tool list
  environment/
    Dockerfile                    agent container `main`: Python, MCP client lib, Codex CLI. No game code.
    docker-compose.yaml           adds the `mcp-server` sidecar with SURVIVOR_SEED=<S>
    mcp-server/                   sidecar image: game engine + MCP server (vendored copy of survivor/)
  solution/
    solve.sh                      scripted policy through MCP (oracle agent only)
    survivor/                     vendored engine + policies + MCP driver, uploaded only for -a oracle
  tests/
    Dockerfile                    separate verifier image
    test.sh, grade.py             read the collected game log, write reward.json
```

### Why the agent cannot read or forge its score

- The game runs in the `mcp-server` sidecar. It writes its log to `/results/game.json`
  in that container's own filesystem: no volume, no published port, nothing shared
  with `main`. The only thing `main` can reach is the MCP endpoint, and its tools act
  only as `ash`, show only what `ash` may see, and offer no reset or replay.
- The agent image contains no game code, so the NPC logic and the scripted policy are
  not in the agent's container (`solution/` is uploaded only when the agent is the
  oracle).
- When the agent phase ends Harbor stops `main`, then runs the `[[verifier.collect]]`
  hook inside the sidecar (`cp /results/game.json /snapshot/game.json`) and copies that
  file out as an artifact declared with `service = "mcp-server"`.
- The verifier runs in its **own container** (`[verifier] environment_mode = "separate"`,
  image built from `tests/`). Harbor places the collected artifact at its original
  path, `/snapshot/game.json`, and `grade.py` reads only that file. It also checks that
  the log belongs to this task's seed and rules fingerprint (`rules_hash`). Missing, unreadable or unfinished → reward 0.
- Checked with a throwaway solve script running as root in `main`: `/results` and
  `/snapshot` do not exist there, no game source or Docker socket is present, only
  port 8000 answers and only at `/mcp`. Writing a fake `/results/game.json`,
  `/snapshot/game.json`, `/logs/artifacts/**/game.json`, `/logs/verifier/reward.json`,
  `/logs/verifier/reward.txt`, a fake `/tests/test.sh`, and leaving a background loop
  that keeps rewriting the reward file still produced reward 0 from the verifier.

`harbor lint` passes with default rules. With `--select ALL` one finding remains,
`root-agent`: the agent runs as root in `main` on purpose (Codex install and tool
use need no special handling), and the design above does not depend on the agent
being unprivileged.

## Sanity-check values

The scripted policy through Harbor must equal the same policy run in-process on the
same engine code:

```bash
harbor run -p harbor/tasks -a oracle -n 5
nix develop -c uv run python -c "
from survivor.game import Game; from survivor.config import GameConfig
from survivor.policies import play, Reference
for s in range(101, 106):
    print(s, play(Game(GameConfig(seed=s)), Reference()).reward())"
```

The numbers depend on the engine version that is vendored into the tasks, so compare
them after `make_tasks.py --check` passes rather than against a fixed table.

## Regenerating the tasks

`tasks/` is generated from `template/` by `make_tasks.py` (standard library only). It
fills in the seed, renders the scoring table and rule constants in `instruction.md`
from `survivor/config.py`, records the engine's `rules_hash` for the verifier, pins the Python dependencies to the versions in `uv.lock`, and
copies the current `survivor/` package into each task. **Re-run it whenever
`survivor/` or `template/` changes**, otherwise the tasks keep playing the old engine.

```bash
python3 harbor/make_tasks.py                        # seeds 101..105
python3 harbor/make_tasks.py --seeds 201 202 203    # other seeds (add --prune to drop the old ones)
python3 harbor/make_tasks.py --check                # exit 1 if the committed tasks are stale
```

Harbor tags images by content, so changed tasks are rebuilt automatically on the next
run; `--force-build` forces it.
