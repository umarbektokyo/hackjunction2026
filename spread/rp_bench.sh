#!/usr/bin/env bash
# Runs the TypeScript RoutePulse (reference for the Python port in rp/) on our bench seeds.
#   usage: ./rp_bench.sh <typescript dir> [first] [n] [parallel]   logs: logs/rp-ts-bench-N.log, actions: logs/rp-ts-bench-N.jsonl
cd "$(dirname "$0")"; . ./env.sh
export dir=$1 here=$PWD; first=${2:-1}; n=${3:-8}; par=${4:-6}
run() { rm -f "$here/logs/rp-ts-bench-$1.jsonl"; (cd "$dir" && RP_LOG="$here/logs/rp-ts-bench-$1.jsonl" nix shell nixpkgs#bun -c bun starter.ts --level 8 --seed "bench-$1") > "$here/logs/rp-ts-bench-$1.log" 2>&1; echo "bench-$1 $(grep -E '^End|error|Error' "$here/logs/rp-ts-bench-$1.log" | head -2)"; }
export -f run
seq "$first" $((first + n - 1)) | xargs -P "$par" -I{} bash -c 'run {}'
echo "rp_bench done"
