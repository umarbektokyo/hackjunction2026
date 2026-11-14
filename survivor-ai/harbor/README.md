# Survivor as Harbor tasks

Five Harbor tasks, `tasks/survivor-seed-101` … `survivor-seed-105`. They are identical
except for the game seed. In each one the agent plays `ash` in an 8-player elimination
game against 7 deterministic NPCs, only through the `survivor` MCP server. The reward
is the game's own score (`Game.reward()`): 1.0 for winning the jury vote, partial
credit for a losing finalist and for late eliminations, and 0 for a game that was not
played to the end. The exact table is in each task's `instruction.md`; it is rendered
from `survivor/config.py` when the tasks are generated.

Tested with Harbor 0.26.0 and the local Docker environment.

## Run it

All commands are run from `survivor-ai/`. The tasks are committed and self-contained;
nothing has to be built or generated first. Docker must be running.

```bash
alias harbor='uv tool run --from harbor==0.26.0 harbor'   # or: uv tool install harbor==0.26.0
```

| Role | Command | Expected |
|---|---|---|
| **Reference run** (strong model) | `harbor run -p harbor/tasks -a opencode -m anthropic/<strong-model> -k 3` | high mean reward |
| **Evaluated agent** (weaker model) | `harbor run -p harbor/tasks -a opencode -m anthropic/<weak-model> -k 3` | lower mean reward |
| Baseline: do nothing | `harbor run -p harbor/tasks -a nop` | 0 on every task |
| Baseline: stop early | `SURVIVOR_POLICY=stop_early harbor run -p harbor/tasks -a oracle` | 0 on every task |
| Pipeline sanity check (scripted policy) | `harbor run -p harbor/tasks -a oracle` | see table below |

`-k 3` runs three attempts per task (15 trials per model). Add `-n 5` to run five
trials at a time, `-i survivor-seed-101` to run a single task, `-o <dir>` to change the
output directory.

The **reference run and the evaluated agent are the same agent (OpenCode) with
different models**; the gap between them is the result. `-a oracle` is not the
reference: it runs `solution/solve.sh`, a small scripted policy that plays through the
same MCP tools. It exists to prove the pipeline end to end (MCP server, result
collection, separate verifier) without spending LLM credits, and its rewards must
equal an in-process run of the same policy.

The stop-early baseline plays one round passively through MCP and then stops calling
tools. It uses the oracle agent with `SURVIVOR_POLICY=stop_early`, which
`[solution.env]` in `task.toml` passes to `solve.sh` (`reference` is the default,
`passive` also exists). On NixOS without the docker group, wrap the whole command:
`SURVIVOR_POLICY=stop_early sg docker -c "uv tool run --from harbor==0.26.0 harbor run …"`.

### Model names and API keys for OpenCode

Harbor's OpenCode agent requires `-m <provider>/<model>` and reads the provider's API
key from the **host environment** (or from `--env-file <file>`) and forwards it into
the agent container:

| `-m` value | Key that must be set |
|---|---|
| `anthropic/<model-id>` e.g. `anthropic/claude-haiku-4-5` | `ANTHROPIC_API_KEY` |
| `openai/<model-id>` | `OPENAI_API_KEY` |
| `openrouter/<vendor>/<model-id>` e.g. `openrouter/anthropic/claude-haiku-4.5` | `OPENROUTER_API_KEY` |

A different variable can be named with `--api-key-name <VAR>`, a different endpoint
with `--base-url`. `harbor run … --dry-run` prints which key and base URL Harbor
resolved without starting anything. Use the model ids your provider account actually
offers; Harbor does not validate them.

```bash
export ANTHROPIC_API_KEY=...
harbor run -p harbor/tasks -a opencode -m anthropic/<strong-model> -k 3 --job-name reference
harbor run -p harbor/tasks -a opencode -m anthropic/<weak-model>   -k 3 --job-name agent
```

What Harbor does with the task's MCP declaration: `[[environment.mcp_servers]]` in
`task.toml` becomes this entry in `~/.config/opencode/opencode.json` inside the agent
container, so the game tools show up in OpenCode as `survivor_get_state`,
`survivor_vote`, …:

```json
{"mcp": {"survivor": {"type": "remote", "url": "http://mcp-server:8000/mcp", "oauth": false}}}
```

OpenCode is then started as
`opencode --model=<provider>/<model> run --format=json --thinking --dangerously-skip-permissions -- "<instruction.md>"`.
OpenCode 1.19.5 is pre-installed in the agent image the same way Harbor installs it,
so Harbor detects it and skips its per-trial install (about 3 minutes). Checked
without an API key: `harbor run … -a opencode --install-only` succeeds, and
`opencode mcp list` in the agent container reports `survivor … connected`.

### Other agents: Claude Code

`-a claude-code` also works on these tasks without changes. Harbor installs Claude
Code into the agent container at trial start (native installer, about 30 seconds because
the image already has curl, node, npm and procps), writes the MCP server to
`$CLAUDE_CONFIG_DIR/.claude.json` as `{"mcpServers": {"survivor": {"type": "http",
"url": "http://mcp-server:8000/mcp"}}}`, and runs with `--permission-mode=bypassPermissions`.
Authentication is `ANTHROPIC_API_KEY`, or a subscription token:

```bash
# .env:  CLAUDE_CODE_OAUTH_TOKEN=...   (from `claude setup-token`)
#        CLAUDE_FORCE_OAUTH=1          (only needed if ANTHROPIC_API_KEY is also set)
harbor run -p harbor/tasks -a claude-code -m anthropic/<model> -k 3 --env-file .env
```

Checked with `--install-only` (no model call): Claude Code 2.1.325 installs in `main`.

## Where results land

`jobs/<job-name>/` (override with `-o`):

```
jobs/<job>/result.json                               aggregate: mean reward and metrics
jobs/<job>/<task>__<id>/result.json                  one trial
jobs/<job>/<task>__<id>/verifier/reward.json         {"reward": …, "terminal", "placement",
                                                      "rounds_survived", "jury_votes", "promises_broken"}
jobs/<job>/<task>__<id>/verifier/details.json        winner, finalists, elimination order, jury votes, metrics
jobs/<job>/<task>__<id>/artifacts/snapshot/game.json full spectator log of the game (every event and ballot)
jobs/<job>/<task>__<id>/agent/                       agent logs (opencode.txt + trajectory, or oracle.txt)
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
    Dockerfile                    agent container `main`: Python, MCP client lib, OpenCode. No game code.
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
`root-agent`: the agent runs as root in `main` on purpose (OpenCode install and tool
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
