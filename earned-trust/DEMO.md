# Demo script (3 to 4 minutes)

Before: `rm -rf decisions && ./run.sh --reuse-tests`. One page, three panes: what changed on the
left, the code in the middle, the AI's review on the right. Criteria in brackets.

## 0:00 The question (20 s)

"Friday, 4 pm. An agent opens a PR and your name goes on the approval. Is reading the diff line by
line still the right way? We say no: review functions, each with the code around it, read only what
the AI could not prove or refused to decide, and put a named person on every decision."

## 0:20 The change (30 s) [Clarity]

- Top left, **REQ-W3**: "A real exam project, written by a person. We asked an agent (Claude, file
  tools only) to make Option 3 run in a thread. Claude, a separate call, reviewed it."
- Progress: "0 of 3 decisions made, 1 of 1 tests prove the change." Legend at the bottom left.
- Merge is grey: "blocked by 3", each a link. "You always see what stands between you and merge."

## 0:50 One function, whole (60 s) [Evidence]

- **startTurnOver**: called from `Main` line 31 and the test; the whole new function; what it calls.
- Top bar: "1 of 1 proves the change. We ran the test with the change and without it: without, it
  does not compile, so it tests new code. A test that passes both ways gets a dashed dot."
- Right: "Serves REQ-W3-1, 2, 3, 7: every unit is traced to the requirement, or says it is not."

## 1:50 What the AI refused to decide (60 s) [Evidence, Practicality]

- **main()** first: "Should the menu wait for the result? The agent chose not to wait, so the answer
  can land in the middle of the next prompt. That is a product call: Jussi, product owner."
  Pick **Join the thread…**: card turns to Decided, toast with Undo, tick in the list, 1 of 3.
- **Next open item →**: two questions on startTurnOver, concurrency (Leena) and the public API
  (Mikko). "The agent said itself the ticket list is not thread-safe. The AI will not choose."
- Decide both. Merge turns black. Merge. "Recorded with Sara's name, the time, and the dossier hash."

## 2:50 The other repo (20 s)

- Switch to **#2283** (Tieto's C#): "Same tool. Here tests prove the crash fix: they pass with it and
  fail without it with the exact crash from the issue. One helper has no test at all: the approver
  can accept it, but then she answers for it."

## 3:10 Measure and close (30 s) [Measurement]

- "Every decision is stored, so trust is measured: reverts of cleared functions against reviewed
  ones, how often owners overrule the AI's routing, time to merge. A category earns auto-clear
  after clean changes and loses it on the first revert. Rules in the concept card."
- "Humans stay accountable. They're accountable for questions, not lines."

## If asked

- *Limits*: units are split by indentation, not a parser; callers are found by name. Two samples.
- *Is the AI review real?* REQ-W3: yes, cached Claude output. #2283: hand-written, labelled.
- *Tests*: `./test.sh`, 116 unit tests of the tool itself.
- *Failure modes*: LESSONS.md.
