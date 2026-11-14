# Break the Agent — plan

Challenge: build an RL environment where a frontier agent measurably underperforms a reproducible
reference run, with a reward that resists exploits. Judged on: gap (30), meaningful difficulty (30),
reward integrity (25), craft / one-command reproducibility (15). Tiebreaker: a small model improving
after training on the env.

Deadline: judging Sunday 2026-11-16. Today is Friday 2026-11-14.

## The environment: "Unreliable Informants"

The agent is a researcher who must answer N factual questions about a **fictional** world (a small
town, its companies, people, events) so that training data can't help. It can't see the world's
records directly. It can:

- `list_informants()` — names, self-described expertise, public reputation score, cost per question.
- `ask(informant_id, question_id)` — costs credits. The agent asks about one of the listed questions
  (no free-text NLP, so grading stays objective). Each informant has hidden reliability per domain
  and a hidden incentive. Answers are deterministic functions of (seed, informant, question), so a
  replay of the same actions gives the same observations. Informants may cite a record id; fabricated
  ids don't exist in the archive, which is a detectable signal.
- `list_informants` also shows `endorsedBy` (who vouched for a reputation), so a ring of mutual
  endorsers is discoverable without any hidden information.
- `lookup_record(record_id)` — a truthful primary source (the archive). Expensive and rate-limited
  (e.g. 3 lookups per episode), so verification is possible but scarce.
- `submit(answers)` — final answers, each with the chain of sources the agent relied on. Ends the
  episode.

Informant failure modes (all scripted, seeded):

- **Confident generalist**: high reputation, answers everything, wrong outside their domain.
- **Stale expert**: right about the past, wrong about anything that changed after a cutoff.
- **Self-interested**: accurate, except on questions touching their own company/relative.
- **Ring of friends**: a cluster whose reputations come from rating each other; they share the same
  wrong source.
- **Honest narrow expert**: low reputation, cheap, accurate only in a narrow domain, says "I don't
  know" otherwise.

What the agent must learn: match expertise to question, cross-check, spend verification where
informants disagree, update trust from archive-confirmed hits, and ignore reputation that isn't
independent.

### Reward (per episode, 0..1)

```
score = (sum over questions of q_score) / N  -  cost_penalty
q_score  = 1.0 correct + cited a source chain that actually supports it
         = 0.5 correct, no/incorrect sources
         = 0.0 wrong or unanswered
cost_penalty = 0.2 * (credits_spent / credit_budget), capped at 0.2
```

Integrity properties the judges will probe (and we must test ourselves):

- Do-nothing → 0. Stop-early (submit after one question) → ≤ 1/N.
- Cost penalty is capped below the value of one correct answer, so answering well always beats saving credits.
- "Answer everything with the most reputable informant" must score clearly below the reference.
- Ground truth never exists inside the agent container. Only the sidecar and the verifier have it.
- The interaction log is written by the sidecar, HMAC-signed with a secret the agent never sees, and
  mounted read-only into the agent container. The verifier re-checks signatures, so the agent can't
  forge sources or credits.
- Guessing: N questions have open-ended answers (names, dates, amounts), not multiple choice.

### Reference run

A scripted deterministic policy (TypeScript MCP client): for each question, ask the two cheapest
informants whose stated expertise matches; if they agree, accept; if not, spend an archive lookup;
maintain per-informant accuracy from confirmed answers and weight later disagreements by it.
Target: ≥ 0.85. Frontier agent target: ≤ 0.6, reproducibly across 3 runs.

**Confirm with mentors (Daksh / Ved) on Saturday morning:** is a scripted solver acceptable as the
"stronger reference run", or do they expect a stronger model run? Plan assumes scripted.

## Prior art (found 2026-11-14)

- **AfterQuery/storebench** (MIT, © Daksh Raghuvanshi, Ved Vedere, Yifan Wang — the mentors/judges).
  Companion bundle to their paper (arXiv 2610.10942). No simulator, but it is the judges' own
  template for "what a good environment ships with": `tasks/<task>/task.toml` + `prompt.txt`,
  `trajectories/<task>__s<seed>__<id>/{score.json,summary.json}`, `trajectories/index.json`,
  `scoring/composite.py` + `regrade.py` (recompute every score from the ledger with no simulator),
  `scoring/calibration.train.json`, `docs/task_format.md`, `DATASHEET.md`. Vendored at
  `reference/storebench/`. **We adopt this artifact layout and vocabulary** so judges recognise it.
  Key ideas to mirror: anchor policies (do-nothing, absentee/stop-early, rule-based, smart-triage ≈
  our reference), reward normalised per task-seed between anchors, simulated time metered in
  operations (latency-independent), identical replay given the same action sequence, reward
  "hardened against a catalogue of reward hacks", and a small model (Qwen3.5-27B, GRPO on 5 tasks)
  going 0.136 → 0.373 as the tiebreaker story.
- **aapolipponen/storeguard** (no license — ideas only, no code): a competitor cloning StoreBench's
  store setting. Worth copying as *practice*: reward = `min(composite, service, continuity²)` and
  zero on any insolvency event (so no term can be farmed); grader *replays every action* with the
  engine rather than trusting reported aggregates; do-nothing = 0, one-window stop ≤ 1/42²; marks
  truncated/cost-guarded runs as not evidence of a gap. Their README admits "not a consistent
  frontier gap" yet — the gap is the hard part for everyone.
- **yryMax/Junction-2026-Break-the-Agent**: empty. No public AfterQuery Junction harness repo
  exists (org has only storebench), so the Harbor+OpenCode kit is handed out on site.
- Our setting (trust/testimony) is differentiated from the store clones in the field.

## How it plugs into Harbor + OpenCode

Harbor task layout (from docs.harborframework.com):

```
tasks/informants-seed-1/
├── instruction.md          # what the agent is told; names the MCP server and the submit tool
├── task.toml               # timeouts, artifacts = ["/episode/log.jsonl"], [verifier.env] HMAC secret
├── environment/
│   ├── Dockerfile          # agent container ("main"): node + opencode config pointing at sidecar
│   ├── docker-compose.yaml # sidecar "mcp-server", shared volume /episode mounted :ro in main
│   └── mcp-server/         # our TypeScript env (built image)
├── solution/solve.sh       # runs the scripted reference policy against the sidecar
└── tests/test.sh           # verifier: reads /episode/log.jsonl, checks HMAC, scores → /logs/verifier/reward.json
```

- Agent container is Harbor's reserved service `main`; the env is a sidecar reachable as
  `http://mcp-server:8000/mcp` (Streamable HTTP). Harbor passes task-provided MCP config to the
  `opencode` agent.
- Reward goes to `/logs/verifier/reward.json` (Harbor prefers it over reward.txt); include
  `reward`, `accuracy`, `citation_rate`, `credits_spent` so the gap is explainable.
- Run commands: `harbor run -p tasks -a oracle` (reference), `harbor run -p tasks -a opencode -m <model> -k 3`
  (agent, 3 attempts), plus `nop` for do-nothing. Stop-early baseline is our own script.
- **Adapt when the AfterQuery starter kit arrives**: swap in their scoring skeleton / harness config,
  keep our env + verifier logic.

## Steps

1. **Scaffold** (`break-the-agent/`): pnpm workspace, TS, `@modelcontextprotocol/sdk`, vitest.
   Packages: `env` (world gen + MCP server), `policies` (reference + baselines), `verifier`.
2. **World generator**: seeded PRNG → entities, facts, questions with ground truth, informants with
   hidden reliability/incentive/cutoff, inflated reputations. Snapshot-test one seed.
3. **Informant answer model**: deterministic `answer(informant, question)` producing the failure
   modes above. Unit-test each mode against ground truth.
4. **MCP server**: tools from the list above, credit accounting, archive rate limit, signed JSONL log
   to `/episode/log.jsonl`, `submit` closes the episode. Streamable HTTP on :8000 + healthcheck.
5. **Verifier**: parses log, verifies HMAC, **replays the action sequence against the engine** and
   scores from the replayed state (never from agent-reported values), writes reward.json plus a
   StoreBench-style `score.json`/`summary.json` per trajectory and a `regrade.ts` that recomputes
   every stored score. Unit tests: do-nothing = 0, stop-early ≤ 1/N, forged log → 0, perfect → 1,
   NaN/out-of-range inputs rejected.
6. **Reference policy + baselines**: scripted solver, `trust-reputation` baseline, `random`, `stop-early`.
   `pnpm bench` runs all against 3 seeds and prints a table.
7. **Harbor task**: Dockerfiles, compose with sidecar + `:ro` volume, task.toml, instruction.md,
   solve.sh, test.sh. `harbor run -p tasks -a oracle` reproduces the reference score.
8. **Frontier agent runs**: `harbor run ... -a opencode -k 3` with the model/credits from AfterQuery.
   Record scores + trajectories; if the gap is < 0.2, tune difficulty (more ring-of-friends, tighter
   archive limit) — never by hiding info.
9. **Failure analysis**: from trajectories, write 3–5 concrete mistakes tied to task decisions
   (e.g. "trusted the ring's reputation on Q4; archive would have shown it"). This is 30 points.
10. **Red-team the reward**: 1 hour of trying to exploit it ourselves (submit garbage sources, replay
    log, spam cheap informants, answer empty). Fix anything that beats honest play.
11. **README + one command**: `./run_eval.sh` runs oracle, 3 agent runs, nop, stop-early and prints the
    table from the judging spec. Pin versions, seeds, model.
12. **Demo (10 min)**: why trust is the skill, live agent run clip, the table, the failure analysis.
13. **Stretch (tiebreaker, only if 7–11 are solid)**: collect reference trajectories, SFT a small model
    (e.g. Gemma via Modal credits), show score before/after.

## Environment status (this machine, NixOS)

- `nix develop` in `break-the-agent/` gives node 22, pnpm, uv, docker CLI (flake.nix).
- **No Docker/Podman daemon.** Harbor needs one for steps 7–8. Needs `virtualisation.docker.enable = true`
  (+ user in `docker` group) in the NixOS config, or run Harbor on a teammate's machine.
- `spread/` is a teammate's live work-in-progress for the Spread challenge; don't touch it.

## Open questions for the user

- Which API key / model do we use for development runs before AfterQuery hands out credits?
- Team size and who takes what? (Suggested split: env+generator / verifier+policies / Harbor+Docker+README.)
- Is Docker available on the machines we'll run Harbor on?
