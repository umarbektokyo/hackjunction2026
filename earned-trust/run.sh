#!/bin/sh
# One command: fetch the sample repo if missing, rebuild the dossier, open the reviewer in the browser.
set -e
cd "$(dirname "$0")"
[ -d sample-repo ] || git clone -q -b ju26-issue-2283 https://github.com/te-industry-tech-office/junction26-messagepack-csharp sample-repo
python3 -m trust.build 2283
exec python3 -m trust.serve 2283 "$@"
