#!/usr/bin/env bash
# usage: ./sweep.sh SEEDS 'name {json}' 'name {json}' ...
cd "$(dirname "$0")"; . ./env.sh
n=$1; shift
for cfg in "$@"; do "$SPREAD_PYTHON" bench.py --name "${cfg%% *}" --seeds $n --params "${cfg#* }" 2>&1 | grep -E 'ERROR|mean margin'; done
