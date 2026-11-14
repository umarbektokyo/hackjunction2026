#!/bin/sh
# One command: build the sample repos, rebuild every case's dossier, open the reviewer at :8283.
# Tests run when the toolchain exists (.NET 8 for #2283, a JDK for REQ-W3), else they show "not run".
# Pass --reuse-tests to rebuild without running them again.
set -e
cd "$(dirname "$0")"
./samples.sh
for case in input/*/case.json; do
    python3 -m trust.build "$(basename "$(dirname "$case")")" "$@"
done
exec python3 -m trust.serve
