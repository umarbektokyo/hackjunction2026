#!/bin/sh
# Every unit test: Python (builder, test runners, style, decisions, server) and JavaScript (page logic and views).
# Needs python3 and node 22; neither runs the sample projects.
set -e
cd "$(dirname "$0")"
python3 -m unittest discover tests
cd web && node --test test/*.test.js
