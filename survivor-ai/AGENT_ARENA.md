# Command-driven agent arena

The optional arena lets a researcher run a local executable at one or more Survivor
seats. The executable can wrap any LLM or agent framework; Harbor's judged tasks
continue to use their existing deterministic NPCs.

From `survivor-ai/`, run one command at every seat:

```bash
python -m survivor.agent_arena --all-seats-command "python /absolute/path/to/agent.py" --seeds 101-105
```

Or use a separate evaluated agent and opponent controller, leaving the other seats
scripted:

```bash
python -m survivor.agent_arena \
  --ash-command "python /absolute/path/to/target_agent.py" \
  --opponent-command "python /absolute/path/to/opponent_agent.py" \
  --opponent-seats bea,cyd \
  --seeds 101-105
```

Each decision starts a fresh process. It receives one JSON request on stdin and must
print one JSON object to stdout. The request includes:

- `protocol`: `survivor-agent-v1`
- `seat`: the player's name
- `decision`: `discussion_action`, `vote`, `jury_vote`, or a response decision
- `observation`: only that seat's visible game state and event history
- `private_context`: that seat's seeded private remove/protect objective and reservation
  slack
- `context`: decision-specific legal targets or a pending offer

Responses are `{"action": {...}}` for discussion actions, `{"target": "..."}` for a
vote, `{"finalist": "..."}` for a jury vote, and `{"accept": true}` or
`{"accept": false}` for offers. Invalid output falls back to pass, a legal vote, or a
declined offer and is recorded in that seat's private event log.

The default is one discussion slot per player per round to keep model calls tractable;
set `--discussion-turns` from 1 to 4 to change it. Per-decision timeout defaults to 90
seconds. The arena writes live atomic snapshots and run metadata under
`results/runs/arena-*`, which the [dashboard](dashboard/README.md) can observe.

This is a local research harness, not a sandbox for untrusted submissions. The
configured executable runs with the current user's environment and may use credentials
available to that user. The harness sends it only that seat's game observation, but
process isolation must be added before running code from untrusted researchers. The
full spectator artifact includes private game information for analysis; it is not sent
to any participant.

The controller command itself is not saved because command arguments can contain
secrets. Record the model, prompt version, sampling settings, and wrapper revision with
the experiment label so runs can be reproduced. Run several seeds and repetitions;
the game seed fixes environment randomness but does not make an LLM deterministic.
