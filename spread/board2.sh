#!/bin/bash
cd "$(dirname "$0")"; . ./env.sh
while pgrep -f 'bot.py --board' >/dev/null; do sleep 5; done
for i in 2 3 4 5; do ../.venv/bin/python bot.py --board --params '{"fee_open": 0.8, "fee_cap": 1.7, "target_win": 0.4, "max_minutes": 180, "min_drivers": 20, "fee_clock": 1, "past_saving": 1}' --quiet --json; done
