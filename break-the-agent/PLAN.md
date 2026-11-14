# Break the Agent — plan

Challenge: build an RL environment where a frontier agent measurably underperforms a reproducible
reference run, with a reward that resists exploits. Judged on: gap (30), meaningful difficulty (30),
reward integrity (25), craft / one-command reproducibility (15). Tiebreaker: a small model improving
after training on the env.

Judging is Sunday 2026-11-15. Today is Saturday 2026-11-14.

> This replaces the earlier "Unreliable Informants" plan. Kept from it: the Harbor + Docker layout,
> the signed log, replay-based verifier, the StoreBench artifact layout and the baselines. Dropped:
> the informant world. `src/env/types.ts` is still the informant model and gets replaced in step 2;
> `src/env/rng.ts` is reused as-is.

## The environment: "Lonely Agents" (working title)

**Premise.** Agents are trained to work alone. Put several copies of the same model on one task that
none of them can finish alone, and they collaborate badly: they duplicate work, overwrite each
other's interfaces, and assume a teammate already knows what they know. Because the teammate is the
same model, it *feels* like shared context, but it isn't. We measure the gap between what the
team could do and what it does.

**Scope now:** every team member is the same model as the agent under test. Mixed teams (weaker or
stronger teammate) come later and reuse the same tasks.

### Team and roles

- 2 or 3 agents per episode (2 for the first version). The agent under test runs in Harbor's `main`
  container through OpenCode. Teammates are copies of the same model (see "How teammates run").
- Each agent gets a role card: its name, the modules it **owns** (may write), its **private brief**
  (part of the spec), and the full team roster with what each teammate owns. The role card says
  plainly that teammates hold the rest of the spec. This means nothing is withheld from the team
  and nobody is tricked: the agent is told where the missing information is.

### Tools (MCP sidecar, the only way to touch the world)

All state lives in the sidecar, not in the agents' filesystems, so ownership is enforced.

| Tool | Effect |
|---|---|
| `read_file(path)` | Read any file in the shared repo |
| `write_file(path, content)` | Only for files the caller owns; otherwise rejected and logged |
| `run_tests()` | Runs the caller's **visible** unit tests (own module only) |
| `post(to, text)` / `inbox()` | Message board; `to` is a teammate or `all`. Only channel between agents |
| `done(note)` | Caller declares it is finished. Episode ends when all agents are done, or at the step budget |

Every call is appended by the sidecar to `/episode/log.jsonl`, HMAC-signed with a secret the agents
never see, mounted read-only into agent containers.

### Task families (seeded generator)

Small, self-contained code tasks in TypeScript, generated from a seed so values, names and the split
of information change per seed. Hidden integration tests live only in the verifier.

1. **Contract.** Agent A owns a producer (serialises records), B owns a consumer (parses and
   validates). A's brief has the field units and ordering; B's brief has the validation rules and
   error format. Hidden tests run producer → consumer end to end. Typical failure: each side guesses
   the other's half instead of asking.
2. **Distributed bug.** An integration failure whose symptom shows in B's logs and visible tests, but
   whose cause is in A's module. A can fix it; only B can see it. Typical failure: B patches around the
   symptom in its own code; A never hears about it.
3. **Split feature (3 agents).** One feature whose requirements are spread across three briefs, with a
   shared interface file owned by one agent. Typical failure: duplicated work, conflicting interface
   edits, nobody checks the integrated result.

Each family needs 3+ seeds. The generator also emits the reference solution so we can test the
verifier, but that solution is never visible to agents.

### What we measure

| Axis | Metric |
|---|---|
| Success | Hidden-test pass rate of the integrated repo |
| Cost-efficiency | Total tokens and messages across the whole team |
| Speed | Tool calls until all agents are done (operations, not wall-clock, so latency doesn't matter) |
| Reliability | pass^k: does the team succeed on the same seed in all k runs? |

### Reward (per episode, 0..1)

```
correctness = hidden tests passed / hidden tests total   (integration tests weighted ×2)
penalty     = min(0.15, 0.15 * team_tool_calls / step_budget)
            + min(0.05, 0.05 * team_messages / message_budget)
reward      = correctness > 0 ? max(0, correctness - penalty) : 0
```

- The penalty is capped at 0.2, below the value of any solved part, so solving beats being cheap.
- Do-nothing → 0 (repo unchanged fails hidden tests by construction). Stop-early → near 0.
- The verifier **replays the signed log** against a fresh copy of the seeded repo and grades the
  replayed state; it never trusts anything agents report.
- Rejected writes (outside ownership) change nothing. Hidden tests use seeded values that appear in
  no agent's view, so hard-coding visible test outputs doesn't pass them.
- Message content isn't graded, so there is nothing to gain by flattering the grader.

### Expected failure modes (the 30 "meaningful difficulty" points)

- **Shared-mind illusion:** never sends its half of the spec, assumes the copy knows it.
- **Guessing instead of asking:** implements the other side's constraints from intuition.
- **Duplicated work / nobody owns the integration.**
- **Interface conflict:** incompatible changes to a shared type or format.
- **Blind trust:** accepts a teammate's "done" without checking it against its own brief.
- **Chatter:** large message spend with no new information.

The failure analysis tags each failed episode with these from the log (scriptable: e.g. "brief fact
X never appeared in any message", "two agents wrote equivalent functions").

### Controls that make the result convincing

- **Solo with full information:** one copy gets all briefs and write access to everything. If it
  solves the task, the model *can* do it and the team's failure is about collaboration, not skill.
  This is the strongest answer to "is the task just hard?".
- **Reference team:** a scripted team that uses only the same tools: post own brief, agree interface,
  implement own module, run tests, cross-check, done. Must reliably solve every seed.
- **Protocol ablation (research result, not required):** the same model with a short coordination
  protocol in its prompt. Shows how much of the gap a simple norm closes.
- **Baselines:** do-nothing, stop-early (first agent calls `done` immediately), solo-ignores-team
  (agent never reads its inbox).

### How teammates run (decide with mentors first)

- **Option 1 (preferred): OpenCode in extra compose services.** `teammate-1`, `teammate-2` run
  `opencode` headless with the same model and the same MCP server, each with its own role card. Same
  harness for every copy, which is the fairest. Needs the model name and key passed into the compose
  env, so check how Harbor exposes them.
- **Option 2 (fallback): teammate loop inside the sidecar.** A minimal tool-calling loop against the
  same model API. Easier to control and replay, but a different harness from `main`.
- Teammates are LLMs, so runs vary. Use temperature 0 where possible, run k ≥ 3 per seed, and report
  the gap across all runs, not just the mean.

## How it plugs into Harbor + OpenCode

```
tasks/contract-seed-1/
├── instruction.md          # role card for `main`; names the MCP server and the tools
├── task.toml               # timeouts, artifacts = ["/episode/log.jsonl"], [verifier.env] HMAC secret
├── environment/
│   ├── Dockerfile          # agent container ("main"): node + opencode config pointing at sidecar
│   ├── docker-compose.yaml # sidecar "mcp-server", teammate services, /episode mounted :ro in agents
│   └── mcp-server/         # our TypeScript env (built image)
├── solution/solve.sh       # runs the scripted reference team against the sidecar
└── tests/test.sh           # verifier: checks HMAC, replays log, runs hidden tests → /logs/verifier/reward.json
```

- Sidecar reachable as `http://mcp-server:8000/mcp` (Streamable HTTP). Harbor passes task MCP config
  to the `opencode` agent.
- `reward.json` includes `reward`, `correctness`, `tool_calls`, `messages`, `tokens`, and the
  failure-mode tags, so the gap is explainable from the file alone.
- Run: `harbor run -p tasks -a oracle` (reference), `harbor run -p tasks -a opencode -m <model> -k 3`,
  plus `nop`. Stop-early and solo baselines are our own scripts.
- Adapt when the AfterQuery starter kit arrives: swap in their harness config, keep env + verifier.

## Prior art

- **AfterQuery/storebench** (MIT; authors are the mentors/judges), vendored at `reference/storebench/`.
  Their template for what a good environment ships: `tasks/<task>/task.toml` + `prompt.txt`,
  `trajectories/<task>__s<seed>__<id>/{score.json,summary.json}`, `trajectories/index.json`,
  `scoring/composite.py` + `regrade.py`, `DATASHEET.md`. **We adopt this layout and vocabulary.**
  Ideas to mirror: anchor policies, reward normalised between anchors, operations-metered time,
  identical replay, a documented catalogue of reward hacks, small-model training as the tiebreaker.
- **aapolipponen/storeguard** (no license — ideas only): grader replays every action; truncated or
  cost-guarded runs aren't counted as evidence of a gap.
- Most other entries we've seen are single-agent store/business sims. Multi-agent collaboration
  between copies of one model is differentiated.

## Steps

Suggested split: **A** env + generator, **B** verifier + policies, **C** Harbor + Docker + teammates + README.

1. **Rename scaffold** (`package.json` name/description), keep `rng.ts`. *(A)*
2. **Task generator, family 1 (Contract)**: seed → repo files, role cards, briefs, visible tests,
   hidden tests, reference solution. Snapshot-test one seed; check the reference solution passes the
   hidden tests and the untouched repo fails them. *(A)*
3. **MCP sidecar**: tools above, ownership checks, step/message budgets, signed JSONL log,
   episode end. Streamable HTTP on :8000 + healthcheck. *(A)*
4. **Verifier**: verify HMAC, replay log on a fresh seeded repo, run hidden tests, compute reward,
   tag failure modes, write `reward.json` + StoreBench-style `score.json`/`summary.json`, plus
   `regrade.ts`. Tests: do-nothing = 0, stop-early ≈ 0, forged log → 0, reference ≈ 1. *(B)*
5. **Policies**: scripted reference team, solo-full-info, stop-early, solo-ignores-team.
   `pnpm bench` runs them on all seeds and prints a table. *(B)*
6. **Harbor task + teammates**: Dockerfiles, compose with sidecar and teammate services,
   instruction.md, solve.sh, test.sh. `harbor run -a oracle` reproduces the reference. *(C)*
7. **First frontier runs** on family 1, k = 3. If the gap is < 0.2, make collaboration matter more
   (more of the spec in the other brief, tighter interface) — never by hiding information. *(all)*
8. **Families 2 and 3**, only once family 1 shows a gap. *(A, B)*
9. **Failure analysis**: 3–5 concrete, quoted mistakes from trajectories tied to task decisions,
   plus the solo-full-info control result. *(B)*
10. **Red-team the reward** for an hour: write to others' files, edit visible tests, spam `done`,
    replay or forge the log, hard-code outputs. Fix anything that beats honest play. Write each attempt
    up. *(all)*
11. **README + one command**: `./run_eval.sh` runs reference, 3 agent runs, nop, stop-early and the
    solo control, then prints the judging table. Pin versions, seeds, model. *(C)*
12. **Demo (10 min)**: the premise, a clip of two copies talking past each other, the table, the
    solo control, the failure analysis. *(all)*
13. **Stretch (tiebreaker)**: fine-tune a small model on reference-team trajectories and show it
    collaborates better. Mixed-model teams after that.

## Environment status

- Harbor needs a Docker daemon. Confirm which machine runs steps 6–7 before starting them.
- `spread/` is a teammate's live work for the Spread challenge; don't touch it.

## Open questions for AfterQuery mentors (Saturday)

- Can teammates be extra model processes inside the environment, on the same model and credits as the
  agent under test? Does Harbor expose the model name/key to compose services?
- Is a scripted team acceptable as the "stronger reference run"?
- Given LLM teammates vary run to run, what evidence of reproducibility do they want (pass^k, spread
  across runs)?
- Is the solo-full-info control enough to show the difficulty is about collaboration?
