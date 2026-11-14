#!/usr/bin/env sh
# Review Tieto's four agent-written branches. Usage: ./review-all.sh <path-to-sample-repo> [--exec]
set -eu
REPO="${1:?path to junction26-messagepack-csharp clone}"
shift || true
cd "$(dirname "$0")"
for id in 2234 2283 2297 2129; do
  echo "== REQ-$id"
  node dist/cli.js review --repo "$REPO" --base origin/HEAD --head "origin/ju26-issue-$id" \
    --requirement "requirements/REQ-$id.md" --out "reports/REQ-$id" --concurrency 4 "$@"
done
echo "== summary"
for id in 2234 2283 2297 2129; do
  node -e 'const r=require(process.argv[1]);console.log(`REQ-'$id': ${r.recommendation}  supported=${r.verdicts.filter(v=>v.verdict==="supported").length} contradicted=${r.verdicts.filter(v=>v.verdict==="contradicted").length} unverifiable=${r.verdicts.filter(v=>v.verdict==="unverifiable").length}  risk=${r.facts.riskTier}  $${r.costUsd}`)' "./reports/REQ-$id/report.json"
done
