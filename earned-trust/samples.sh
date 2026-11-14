#!/bin/sh
# Build the sample repositories the reviewer reads. Safe to re-run: existing ones are kept.
#   sample-repo/    Tieto's MessagePack-CSharp fork (branches ju26-issue-*)
#   sample-wadden/  Waddenislands (human-written exam solution) + the agent's branch for REQ-W3
set -e
cd "$(dirname "$0")"
[ -d sample-repo ] || git clone -q https://github.com/te-industry-tech-office/junction26-messagepack-csharp sample-repo

if [ ! -d sample-wadden/.git ]; then
    mkdir -p sample-wadden
    cp -r Waddenislands/src Waddenislands/tests Waddenislands/resources Waddenislands/checkstyle.xml sample-wadden/
    g() { git -C sample-wadden -c user.name=sample -c user.email=sample@localhost "$@"; }
    g init -q -b main
    g add -A && g commit -qm "Waddenislands exam solution (human-written base)"
    g checkout -qb agent/req-w3-thread
    g apply ../input/w3/agent.patch
    g add -A && g commit -qm "Run Option 3 turnover calculation in a separate thread (REQ-W3)" --author="agent <agent@localhost>"
    g checkout -q main
fi
