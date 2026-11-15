# Survivor dashboard

Start the local read-only observer from the repository root:

```bash
python3 survivor-ai/scripts/dashboard.py
```

Open <http://127.0.0.1:8765>. The dashboard watches `survivor-ai/results/runs/` and
refreshes game state every second. Local runs write atomic game snapshots after each
accepted action, so multiple local agent games can be observed at once. Start runs with
`survivor-ai/scripts/local_runs.py` or the [command-driven arena](../AGENT_ARENA.md).
For local Codex runs, Codex CLI must be available and signed in.

Saved Harbor artifacts under `survivor-ai/jobs/` also appear in the run list. Harbor
intentionally keeps its live game log inside the isolated MCP sidecar and only collects
it after the agent stops, so the dashboard can show Harbor games after collection, not
their in-progress state.

This dashboard is a **spectator view**. It can show private messages and hidden NPC
goals/trust from the full local game snapshot; those fields are not shown to the agent.
The server binds to `127.0.0.1` and provides read-only endpoints only.
