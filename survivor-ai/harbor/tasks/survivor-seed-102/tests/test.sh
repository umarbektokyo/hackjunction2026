#!/bin/bash
# Reads the game log collected from the mcp-server sidecar and writes the reward.
python3 /tests/grade.py "${SURVIVOR_GAME_LOG:-/snapshot/game.json}" /logs/verifier
