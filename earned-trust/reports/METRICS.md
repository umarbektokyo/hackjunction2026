# Trust metrics

Computed by `cev metrics` from `reports/*/report.json` and `decisions/log.jsonl`. Nothing here is typed in by hand.

## Per change

| Change | Risk | Changed lines | Read by model | Claims (S / C / U) | Routed | Human reads (lines in places) | Recommendation | Decision | Agreed | Min. to decision | Model cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| REQ-2129 | high | 1043 | 1018 | 14 (14 / 0 / 0) | 0 | 0 in 0 | needs-human | pending |  |  | $1.6 |
| REQ-2234 | low | 266 | 266 | 14 (11 / 3 / 0) | 3 | 254 in 11 | reject | pending |  |  | $1.961 |
| REQ-2283 | low | 228 | 228 | 13 (9 / 3 / 1) | 4 | 265 in 13 | needs-human | pending |  |  | $1.583 |
| REQ-2297 | medium | 1392 | 182 | 13 (12 / 0 / 1) | 1 | 42 in 1 | needs-human | pending |  |  | $1.342 |

## Across changes

| Measure | Value | What it tells you |
|---|---|---|
| Changes routed to a human | 4 of 4 | Share the AI would not clear alone. Should fall per category only while reverts stay flat. |
| Claims routed to a human | 8 of 54 (15%) | The questions the AI refused to decide. |
| Review load | 561 lines in 25 places, against 2929 changed lines | Lines cited as evidence for the routed items, including unchanged code the question needs. A full read is the whole diff plus that context. |
| Findings (contradicted claims) | 6 | What the AI found that the change gets wrong. |
| Findings accepted by the human | no decisions yet | Are the findings real? Rejected findings are false alarms and count against the verifier. |
| Human agreed with recommendation | no decisions yet | An override is logged with its reason. |
| Time to decision (median) | no decisions yet | From report generated to signed decision. |
| Model cost | $6.49 | For all reports. |
| Reverts and incidents of accepted changes | not measurable yet | Needs merges. Source: `git log --grep "This reverts commit <headSha>"` and incident links on the merged SHA. The first revert in a category narrows auto-clear for it. |
