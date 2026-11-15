#!/usr/bin/env bash
cd "$(dirname "$0")"; . ./env.sh
for i in 1 2 3 4 5; do "$SPREAD_PYTHON" bot4.py --board --quiet --json; done
