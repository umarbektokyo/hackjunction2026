#!/usr/bin/env bash
# Plays this round's five level 8 ranking runs with the RoutePulse port.
cd "$(dirname "$0")"; . ./env.sh
for i in 1 2 3 4 5; do
  "$SPREAD_PYTHON" bot4.py --board --quiet --json
done
