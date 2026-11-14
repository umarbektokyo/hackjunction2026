# Demo script (3 to 4 minutes)

Before: `rm -rf decisions && ./run.sh`. One page, three panes: changed functions on the left, the
editor in the middle, the AI's review on the right. Criteria in brackets.

## 0:00 The question (20 s)

"Friday, 4 pm. An agent opens a PR for MessagePack issue 2283, a crash in the source generator, and
your name goes on the approval. Is line-by-line review of files still the right way? We say no.
Review functions, not files, each with the code around it, and read only what the AI could not
prove or refused to decide."

## 0:20 The list (30 s) [Clarity]

- Left pane: "It looks like a Git client, but the unit is a function, not a file. 13 changed
  functions, tests and doc sections. A black dot is checked and safe to skip. A ring is waiting
  for a test run. Orange needs a person."
- "Six of thirteen are dots. Nobody has to read those."

## 0:50 One function, with its surroundings (70 s) [Evidence]

- Selected: **TypeCollector()**, orange. Middle pane, top to bottom:
  - **Mentions**: "Where it is called from, with the real lines: Collect, which is reached from
    the analyzer and from the generator."
  - **Change**: "One line."
  - **Calls**: "What it calls: the new filter, ReportIfLocatedInCompilation." Click the name to
    walk there, then go back.
- "One line, but the code around it shows that every analyzer diagnostic now passes through that
  filter. This is our `*` wildcard moment: harmless in a diff, visible once you see what it touches."
- Right pane: "The AI will not decide this. It names the owner, Aino, asks one question and says why."

## 2:00 Tests (40 s) [Evidence]

- Top bar of the editor: "Three rings: 3 tests cover this function, none has run. We never show
  a test as passing unless it ran."
- Left pane: "The tests that belong to this function stay dark, with the helpers they call; the
  rest go grey." Click a test: the tests of the same code stay lit.
- Click **GetPropertyIdentifierLocation**: "No test reaches this function. It says so in orange,
  and every test greys out."
- Right pane, **the AI noticed**: open "The new tests do not reach either…" on **GetObjectInfo**.
  "Two tests the AI suggests, inside the note that explains why."
- Middle pane on **GetObjectInfo**, line 1077: "Only the part that changed is highlighted:
  `[0]` became `FirstOrDefault()?`."

## 2:40 Decide (40 s) [Practicality]

- Back on **TypeCollector()**: click **Narrow the filter…**. "Recorded with her name, the time,
  the evidence and the hash of this exact dossier."
- **Generic types from referenced assemblies** (docs): click **Keep the fix, drop the docs promise…**.
- Bottom left: "Merge belongs to Sara and still waits for a test run. The tool will not let her
  approve on missing evidence. In a real flow CI fills that in."

## 3:20 Measure and close (30 s) [Measurement]

- "Every decision and check is stored, so trust can be measured: reverts of skipped functions
  against human-read ones, how often owners change what the AI routed, time to merge. A category
  of change earns auto-skip after 50 clean changes and loses it on the first revert. The numbers
  for this change and the rules are in the concept card."
- "Humans stay accountable. They're accountable for questions, not lines."

## If asked

- *UI changes*: the sample is a C# library with no user interface, so there is no visual
  before/after pane. The right pane is where it would go.
- *Limits*: functions are split by indentation, not a parser. Mentions and calls are found by
  name. One sample. The AI's review text is hand-written here (no API key). See CONCEPT.md.
- *Failure modes*: see LESSONS.md.
