#!/usr/bin/env bash
# Runs the with/without benchmark of bot2.py, one bench after another, on 7 practice slots.
#   usage: ./ml_bench.sh 'name|bot|first|{json}' ...      e.g. './ml_bench.sh "ml|bot2.py|1|{}"'
cd "$(dirname "$0")"; . ./env.sh
for cfg in "$@"; do
  IFS='|' read -r name bot first params <<< "$cfg"
  "$SPREAD_PYTHON" bench.py --name "$name" --bot "$bot" --first "$first" --seeds 8 --jobs 7 --params "$params" 2>&1 | grep -E 'ERROR|mean margin'
done
echo "ml_bench done"
