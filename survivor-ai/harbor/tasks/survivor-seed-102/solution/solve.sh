#!/bin/bash
# Pipeline sanity check: plays a scripted policy through the same MCP tools the
# agent uses. SURVIVOR_POLICY comes from [solution.env] in task.toml
# (reference by default; stop_early / passive are baselines).
set -euo pipefail

POLICY="${SURVIVOR_POLICY:-reference}"
case "$POLICY" in
  reference|stop_early|passive) ;;
  *) echo "unknown SURVIVOR_POLICY: $POLICY" >&2; exit 2 ;;
esac

cd "$(dirname "$0")"
python -m survivor.mcp_driver --url "${SURVIVOR_MCP_URL:-http://mcp-server:8000/mcp}" --policy "$POLICY"
