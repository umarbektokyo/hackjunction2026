# Trust report — REQ-2234 · `origin/ju26-issue-2234`

**Recommendation: REJECT — evidence contradicts the change or a requirement item is not met**

- 2 claim(s) contradicted by evidence: C7, C8
- requirement items not met: N1

> The change makes the TypeCollector tolerate duplicate keys and mixed key kinds (skip the member after reporting the diagnostic, guard dictionary Add) so the analyzer no longer throws on suppressed types. It adds analyzer tests for suppressed types, an execution test, and a README section describing analyzer behaviour. The diff does not show the code that makes the analyzer run for SuppressSourceGeneration=true types, so the core fix is unclear from the shown hunks.

## At a glance

| | |
|---|---|
| Requirement | REQ-2234 (`requirements/REQ-2234.md`) |
| Change | `origin/HEAD` → `origin/ju26-issue-2234` (9007cee116) |
| Risk tier | **low** — no flags |
| Files | docs 1, source 1, test 2 |
| Claims | 14: 11 supported, 3 contradicted, 0 unverifiable |
| Execution evidence | Execution evidence disabled (run with --exec to run the added tests and the mutation check). |
| Model | sonnet; cost ≈ $1.961; generated 2026-11-14T03:29:51.926Z |

## Requirement coverage

| Item | Status | Via | Note |
|---|---|---|---|
| **F1** For a type with `SuppressSourceGeneration = true`, the analyzer reports MsgPack004 (member… | partial | C2, C3, C4 | Supported: MsgPack015 and MsgPack003 on suppressed types (C2), plus MsgPack005 duplicate/mixed-key handling without crashing (C3, C4). MsgPack004 is only shown by C1, which is contradicted, so it has no supported claim. MsgPack012 has code reading only (C2) and no test. C8 is contradicted: no change to a skip path for suppressed types was found, so the 3.1.1 regression fix is not shown. |
| **F2** Generation-only diagnostics (MsgPack011 partial class, MsgPack016/017 AOT) are not reporte… | addressed | C5, C9 | MsgPack011 and MsgPack017 are gated for suppressed types and covered by a test (C5). MsgPack016 is gated in code (lines 921-948) but has no test. Medium confidence. |
| **F3** No formatter is generated for these types (existing behaviour preserved). | addressed | C6 | The skip branch is intact and new tests assert a null generated formatter and a dynamic round-trip. Medium confidence. The null return and the dynamic resolver at run time are assumed, not observed. |
| **N1** Regression tests cover F1 for at least MsgPack004 and MsgPack015 and prove the analyzer ru… | contradicted | C7 | C7 is contradicted. The MsgPack004 and MsgPack015 tests probably already pass at BASE, so they do not prove the regression or that the analyzer runs on suppressed types because of this change. Only the duplicate-key and mixed-key tests probably fail at BASE. BASE pass/fail was inferred, not run. |
| **N2** No unrelated dependency or build changes. | partial | C14, C12, C11 | No dependency or build file changes appear (C14, medium). Same-line-count in-place edits and CI files were not excluded. The change also does things nobody asked for: an unrequested README section (C12) and changed collection behaviour for generated types (C11). The human should decide whether to accept both. |

## Claims and verdicts

### ❌ C1 · behaviour · contradicted (medium, minor)

**Claim:** The analyzer now reports MsgPack004 for a member without Key/IgnoreMember on a type marked SuppressSourceGeneration = true. _(→ F1, N1)_

**Basis:** Direct reading of the analyzer entry point and the MsgPack004 path in HEAD and BASE. The diff hunks were also read. Nothing was executed.

**Reasoning:** The MsgPack004 path is unchanged between BASE and HEAD, and BASE already runs Collect on suppressed types. So HEAD does report MsgPack004 for a member without Key/IgnoreMember on a suppressed type, but the diff did not cause that. The word "now" is not supported by the diff. What the diff does change is the duplicate-key and mixed-key handling, which could previously throw. That is a different behaviour from the one claimed. I did not find any BASE code that skips suppressed types, and nothing was run to see BASE fail. A possible BASE failure outside TypeCollector (for example a thrown exception that masks all diagnostics) is not ruled out, and that is why confidence is only medium.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:426-432` — AnalyzeSymbol calls TypeCollector.Collect for any class or struct with [MessagePackObject]. It does not check SuppressSourceGeneration. The BASE file calls Collect at line 430 as well.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1078-1088` — MemberNeedsKey (MsgPack004) is created and reported when `derivedKeyAttribute is null || suppressSourceGeneration is not true`. A plain member without Key/IgnoreMember satisfies this on a suppressed type. BASE has the same MemberNeedsKey creation at line 1077.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1383-1387` — The suppressSourceGeneration early return happens only after the member diagnostics have been reported. It skips only generation.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1004-1046` — The TypeCollector hunks only add a `continue` after DoNotMixStringAndIntKeys and ContainsKey guards before intMembers.Add and stringMembers.Add. These stop duplicate-key exceptions. They do not touch MsgPack004 reporting.
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:16-30` — MemberWithoutKeyIsReported expects MsgPack004 on a suppressed type. It would only be exercised by the existing Collect path. It does not show that BASE failed this case.

### ✅ C2 · behaviour · supported (medium, minor)

**Claim:** The analyzer now reports MsgPack015 (AllowPrivate required) and MsgPack003 (member type not a MessagePackObject) on suppressed types, identically to non-suppressed types; MsgPack012 is also asserted by README but has no test. _(→ F1)_

**Basis:** Direct code reading of TypeCollector.GetObjectInfo and the analyzer entry path, plus reading the added tests. Execution evidence is disabled, so I did not run the tests.

**Reasoning:** The 015 and 003 code paths run for suppressed types and each has a matching test. MsgPack012 is raised in the TypeCollector constructor (lines 244-249), which has no suppress gate, so the README is plausibly correct. No test confirms it, as the claim says. Not checked: whether the gate in analyzer.cs line 430 or the base behaviour was a different cause, and whether the 003 test passes at runtime.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1366-1387` — At HEAD the MsgPack015 AllowPrivate check runs before the `suppressSourceGeneration is true` early return, so it is reported for suppressed types. In BASE the early return (line 1369) sat before the check.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1050` — Member-type recursion (`CollectCore(item.Type, item)`) happens during member enumeration, before the suppress return. The MsgPack003 report at line 1359 is therefore reached for member types of suppressed types.
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:33-68` — AllowPrivateRequiredIsReported expects MsgPack015 and MemberTypeMustBeMessagePackObjectIsReported expects MsgPack003, both on SuppressSourceGeneration = true types. They exercise the claimed path.
- test `tests/MessagePack.SourceGenerator.Tests/MsgPack012InaccessibleDataTypeTests.cs` — The existing MsgPack012 tests contain no SuppressSourceGeneration usage (grep found 0). The new file also has no MsgPack012 test, so the README's MsgPack012 promise is untested for suppressed types.
- code `README.md:1614-1636` — The README lists MsgPack012 (accessibility) as validated for suppressed types.

### ✅ C3 · behaviour · supported (high, info)

**Claim:** After reporting DoNotMixStringAndIntKeys (MsgPack005), the collector skips (`continue`) the member in both the property and field loops, so a mixed-key member is no longer added to intMembers/stringMembers. _(→ F1)_

**Basis:** Direct code reading of both member loops in HEAD. I did not execute anything.

**Reasoning:** In both the property loop (lines 1005-1009) and the field loop (lines 1145-1149), the report is followed by `continue` inside the mismatch condition. Execution therefore never reaches the intMembers/stringMembers adds for a mismatched member. Every `continue` that skips a mismatched member goes through the else branch of `searchFirst`, so the first member is never skipped this way. Side effect: the same `continue` also skips the later recursive `CollectCore(item.Type, item)` call for that member (line 1050 in the property loop). The claim doesn't mention this, but it doesn't contradict it. The diff also adds `ContainsKey` guards before the Add calls. Those are a separate change, not part of C3.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1003-1027` — Property loop: `continue` sits right after the DoNotMixStringAndIntKeys report, inside the mismatch `if`. The `continue` targets the enclosing property foreach. It runs before the intMembers/stringMembers add code.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1143-1167` — Field loop: same pattern. `continue` at line 1148 follows the report at line 1147 and precedes the member adds.

### ✅ C4 · behaviour · supported (high, info)

**Claim:** Dictionary insertions into intMembers/stringMembers are now guarded by ContainsKey, so duplicate keys report MsgPack005 instead of throwing ArgumentException in the analyzer. _(→ F1)_

**Basis:** Direct code reading of the full attributed-member loops (property and field branches) plus the diagnostic descriptor; no execution or test run.

**Reasoning:** All four attributed-member Add sites (property and field, int and string) are wrapped in ContainsKey checks, and each is preceded by a KeysMustBeUnique report, which is MsgPack005. The claim holds. The diff also adds `continue` after DoNotMixStringAndIntKeys. That is not part of C4, but it removes a related crash. Without it, intKey!.Value could throw a null dereference. I didn't run any tests, so the runtime behaviour is untested.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1012-1043` — Property branch: duplicate int/string key first reports KeysMustBeUnique, then Add is guarded by !ContainsKey, so no ArgumentException.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1154-1181` — Field branch has the same ContainsKey diagnostic followed by a guarded Add for both intMembers and stringMembers.
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:115-117` — KeysMustBeUnique uses id InvalidMessagePackObjectId = MsgPack005 (defined at line 18).
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:834-868` — The ForceMap path's stringMembers.Add calls are also guarded. This is extra to the claim, and harmless.

### ✅ C5 · behaviour · supported (medium, minor)

**Claim:** Generation-only diagnostics MsgPack011, MsgPack016 and MsgPack017 are not reported for suppressed types (the test uses a non-partial class with init-only and private members and expects no diagnostics). _(→ F2)_

**Basis:** Direct code reading of GetObjectInfo's relevant paths plus the test source. Nothing was executed, so I did not observe the test passing.

**Reasoning:** Reading the code, MsgPack011 and MsgPack017 are suppressed for SuppressSourceGeneration=true types. The test's inputs would produce both diagnostics for a non-suppressed type, so the test does exercise those two paths. The member-needs-key and AllowPrivate checks still run, so the remaining members of the test class produce no diagnostics. Weak point: the test never uses a derived KeyAttribute, so MsgPack016 is gated in code (lines 921-948) but the test does not exercise it. The claim's parenthetical describes the test input accurately, but "MsgPack016 not reported" has no test coverage.

**Evidence:**
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:170-192` — SourceGenerationOnlyDiagnosticsAreNotReportedWhenSuppressed: a non-partial public class with AllowPrivate=true, SuppressSourceGeneration=true, a private [Key] field and an init-only property with an initializer. It expects no diagnostics.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:988-996` — MsgPack017 (AOTInitProperty) is only reported when suppressSourceGeneration is not true. The test's init property with initializer would trigger it otherwise.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1382-1415` — When suppressSourceGeneration is true, the method returns null at line 1387. That is before the MsgPack011 (PartialTypeRequired) check at line 1407, which needs nestedFormatterRequired and nonPublicMembersAreSerialized. The private [Key] field sets both flags, so MsgPack011 would fire without suppression.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:921-948` — MsgPack016 (AOTDerivedKeyAttribute) is reported only when suppressSourceGeneration is not true. This path needs a member with a KeyAttribute-derived attribute, which the test does not use.

### ✅ C6 · non-change · supported (medium, info)

**Claim:** No formatter is generated for a SuppressSourceGeneration type, and it round-trips through the dynamic resolver (GetFormatter returns null). _(→ F3)_

**Basis:** Direct code reading of the generator path and the added tests. Nothing was executed, and I did not see the generated resolver output.

**Reasoning:** The claim is a non-change claim about generation being skipped. The skip branch is intact at HEAD and matches base. The new tests assert both halves of the claim: null from the generated resolver, and a working round-trip. I did not find anything in the generator source that would register a formatter for a suppressed type. The generated resolver's GetFormatter returning null for unregistered types is assumed, not seen. The round-trip assertion also relies on StandardResolver reaching the dynamic resolver at run time.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1382-1387` — GetObjectInfo returns null when suppressSourceGeneration is true. CollectObject (lines 678-682) only adds non-null info to collectedObjectInfo, so no formatter is generated. The same early return exists in base (line 1369), so this behaviour is unchanged.
- test `tests/MessagePack.SourceGenerator.ExecutionTests/SuppressedSourceGenerationTests.cs:19-36` — Assert.Null on GeneratedMessagePackResolver.Instance.GetFormatter<SuppressedSourceGenerationType>(). A second test round-trips the type via MessagePackSerializer with Standard options, which uses the dynamic resolver.

### ❌ C7 · tests · contradicted (medium, major)

**Claim:** The new analyzer tests fail without the fix, i.e. they prove the analyzer runs on suppressed types. Nothing in the diff changes how suppressed types reach the analyzer, so they may already pass before the change. _(→ N1)_

**Basis:** Direct code reading of the whole analyzer-to-TypeCollector path at BASE and HEAD, with no execution. The two MsgPack004 and MsgPack015 tests look like they pass at BASE, so the claim fails for them. The duplicate-key and mixed-key tests probably fail at BASE, but I could not confirm that.

**Reasoning:** The claim says the new tests fail without the fix and so prove the analyzer runs on suppressed types. The claim's own caveat points the other way, and the code agrees. The analyzer entry point is identical at BASE and HEAD and does not check SuppressSourceGeneration. At BASE, TypeCollector reports MsgPack004 and MsgPack015 before the suppression early return, and those paths are unchanged. So the MsgPack004 and MsgPack015 tests that N1 requires should already pass at BASE. They do not show the regression, and they do not show that the analyzer ran on a suppressed type only because of this change. Only the duplicate-key and mixed-key tests probably fail at BASE, from the unguarded Add. I found no change in the analyzer or TypeCollector entry path that affects whether suppressed types are analyzed. I did not find where HEAD differs from BASE for the 3.1.1 regression itself. I could not run anything, so the BASE pass/fail result is inferred.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:426-432` — Identical at BASE and HEAD. AnalyzeSymbol calls TypeCollector.Collect for any type with [MessagePackObject]. It never looks at SuppressSourceGeneration, so suppressed types already reach the analyzer at BASE.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1383-1387` — BASE has the same early return at line 1369. It only returns null after the MemberNeedsKey (MsgPack004) and AllowPrivateRequired (MsgPack015) diagnostics have already been reported, so those diagnostics fire at BASE for suppressed types.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1138-1183` — The only hunks in this region that I found differing from BASE (lines 1131-1159) are a `continue` after DoNotMixStringAndIntKeys and `if (!...ContainsKey) Add` guards on the member dictionaries. They stop a duplicate-key or mixed-key crash. BASE calls intMembers.Add and stringMembers.Add unguarded, which would throw on a duplicate key. I read this as a crash fix, not a change to how suppressed types reach the analyzer.
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:16-56` — MemberWithoutKeyIsReported (MsgPack004) and AllowPrivateRequiredIsReported (MsgPack015) cover the two diagnostics N1 names. They exercise code that is unchanged between BASE and HEAD, so they should pass at BASE and do not demonstrate a fix.
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:78-126` — The duplicate-key and mixed-key tests (MsgPack005) probably do fail at BASE, from the unguarded dictionary Add. That makes them regression tests for a crash fix, not proof that the analyzer runs on suppressed types.
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:128-146` — DuplicateKeysAreReportedWithoutAnalyzerFailureForGeneratedTypes uses a plain [MessagePackObject], with no suppression.

**For the human:** Run the new test class against BASE src, for example by stashing the TypeCollector.cs changes. Which tests fail? If MemberWithoutKeyIsReported and AllowPrivateRequiredIsReported pass, where is the 3.1.1 regression fixed, and how do these tests guard it?

### ❌ C8 · behaviour · contradicted (medium, major)

**Claim:** The shown diff fixes the 3.1.1 regression: the code path that skips suppressed types in the analyzer is removed or changed in a file within this change. _(→ F1)_

**Basis:** Direct code reading of the analyzer entry, TypeCollector.Collect, CollectCore, GetObjectInfo and the suppress gate, in both checkouts, plus a grep for every SuppressSourceGeneration use under src. I did not see the full diff, and nothing was executed.

**Reasoning:** The claim says the diff removes or changes a code path that skips suppressed types in the analyzer. In TypeCollector.cs the diff only touches duplicate-key and mixed-key handling. The `suppressSourceGeneration is true` gate is unchanged and still comes after the diagnostics. I found no analyzer-level skip of suppressed types in base or head, so the premise that such a path exists at base is not shown. The diff may fix the user-visible symptom some other way, for example by stopping a duplicate-key exception from aborting analysis. That is a different mechanism from the one the claim names. I only saw the TypeCollector.cs hunks and the other files I opened, so a change elsewhere could still exist.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1383-1387` — The only suppress gate is `if (suppressSourceGeneration is true) return null;`. It sits after the diagnostic reporting and the diff leaves it intact (base line 1369, head line 1383, shifted only by added lines). It skips generation, not analysis.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1002-1046` — The diff hunks add `continue` after the DoNotMixStringAndIntKeys diagnostic and guard `intMembers.Add` / `stringMembers.Add` against duplicate keys. These are duplicate-key and mixed-key robustness changes. None of them touch suppression handling.
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:426-432` — AnalyzeSymbol calls TypeCollector.Collect for any [MessagePackObject] type with no check for SuppressSourceGeneration. Base and head are identical here, so no analyzer-level skip exists to remove.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:263-293` — Collect and CollectCore have no suppress-based early exit at head, and the diff does not change them.

### ✅ C9 · docs · supported (medium, info)

**Claim:** README promises that the analyzer reports MsgPack003/004/005/012/015 for suppressed types and does not report MsgPack011/016/017, with links to doc/analyzers pages. _(→ F1, F2)_

**Basis:** Direct code reading of the analyzer entry and TypeCollector paths, plus a check that the linked doc pages exist. I did not run any tests.

**Reasoning:** Every promise in the README paragraph has code behind it. 003, 004, 005, 012 and 015 are not gated on suppression. 011, 016 and 017 are skipped for suppressed types by the early return and the explicit guards. All eight linked doc pages exist. I did not trace the MsgPack005 code or the MsgPack003 member-type path (CollectCore) end to end. I also did not check whether the README's MsgPack012 wording ("accessible to the resolver") matches that diagnostic's own text. That is why confidence is medium, not high.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:429-430` — The analyzer calls TypeCollector.Collect for any class or struct with [MessagePackObject], with no check for SuppressSourceGeneration.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:921-948` — MsgPack004 (MemberNeedsKey) is reported for suppressed types. MsgPack016 (AOTDerivedKey) is only reported when suppressSourceGeneration is not true.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:989-996` — MsgPack017 (AOTInitProperty) is guarded by suppressSourceGeneration is not true, so it is not reported for suppressed types.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1366-1387` — MsgPack015 (AllowPrivate required) is reported before the suppression early-return at line 1383.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1383-1407` — The early-return for suppressed types comes before the MsgPack011 (PartialTypeRequired) report at line 1407, so MsgPack011 is not reported for them.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:244-249` — MsgPack012 (InaccessibleDataType) is reported in the constructor, independent of the suppression flag.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1351-1364` — MsgPack003 (TypeMustBeMessagePackObject) is reported when a type reached through a member has no [MessagePackObject]. This is not conditioned on suppression of the containing type.
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:24-174` — New tests expect MsgPack004, 015, 003 and 005 on suppressed types. A comment at line 171 says MsgPack011/016/017 are not reported.
- docs `doc/analyzers/MsgPack011.md` — The doc pages linked from the README exist for MsgPack003, 004, 005, 011, 012, 015, 016 and 017.

### ✅ C10 · docs · supported (high, info)

**Claim:** README states suppressed types are not AOT-safe and are serialized by the dynamic (reflection) resolvers.

**Basis:** Direct code reading of the attribute doc and resolver lists, plus the README text.

**Reasoning:** The README sentence matches the attribute's documented behavior and the resolver chain. The README says "use reflection", while the preceding README text says Reflection.Emit. That is compatible: Reflection.Emit is part of System.Reflection and is not AOT-compatible. I did not find any contradiction.

**Evidence:**
- docs `README.md:1620-1623` — New section says no formatter is generated, the type is serialized by the dynamic resolvers (which use reflection), and so is not AOT-safe.
- code `src/MessagePack.Annotations/Attributes.cs:31-43` — SuppressSourceGeneration doc says DynamicObjectResolver will generate a formatter at runtime when no precompiled one is found.
- code `src/MessagePack/Resolvers/StandardResolver.cs:30` — StandardResolver falls back to DynamicObjectResolver; this is the dynamic runtime path.

### ✅ C11 · scope · supported (high, minor)

**Claim:** The ContainsKey guards and `continue` also alter behaviour for non-suppressed (generated) types, which makes a generated-type test (DuplicateKeysAreReported...ForGeneratedTypes) necessary; no requirement asks for changing generated-type collection behaviour.

**Basis:** Direct code reading of GetObjectInfo in HEAD and BASE, plus the added test; no execution.

**Reasoning:** The diff contains the guards and `continue` with no condition on suppression, so generated types take the same path. In BASE, duplicate keys on a generated type led to a bare Dictionary.Add after KeysMustBeUnique was reported. HEAD instead skips the Add, so behaviour for generated types does change. The requirement covers only suppressed types, and the generated-type test exists to cover this side effect. I did not check whether BASE's throw was caught elsewhere, so how bad the old behaviour was for generated types is unknown. The human should decide whether this is acceptable. It plausibly fixes a latent crash that also affected generated types. It could also be argued that F1's MsgPack005 requirement implies it.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1003-1043` — The `continue` after DoNotMixStringAndIntKeys and the `if (!ContainsKey) Add` guards are unconditional. They are not gated on suppressSourceGeneration (read at line 710), so they apply to every type that goes through GetObjectInfo, including generated ones.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1145-1183` — The same unconditional guards in the second member loop (fields).
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1` — BASE had bare `intMembers.Add` / `stringMembers.Add` at lines 1022, 1035, 1155 and 1168 with no guard. A duplicate key on a generated type used to hit Dictionary.Add after the diagnostic. HEAD now skips the Add.
- test `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs:128-147` — DuplicateKeysAreReportedWithoutAnalyzerFailureForGeneratedTypes uses a plain [MessagePackObject] with no suppression. It exists only because the guards also affect generated types.
- docs `REQ-2234` — F1–F3 and N1 only cover suppressed types. None of them mention changing duplicate-key or mixed-key handling for generated types.

### ✅ C12 · scope · supported (high, info)

**Claim:** A new README section 'Opting out of source generation' is added, which no requirement item asks for. _(→ N2)_

**Basis:** Direct code reading of HEAD README.md and a search of BASE README.md; compared against the requirement document.

**Reasoning:** The diff adds the section, and BASE has no mention of the flag. REQ-2234 asks for analyzer behaviour (F1–F3), regression tests (N1) and no unrelated dependency or build changes (N2). It asks for no documentation. The section restates F1 and F2 as user-facing docs, so it is documentation scope the requirement did not request. Its blast radius is documentation only, with no code or build effect. Whether to accept it is the human's decision. I did not check that the linked doc/analyzers pages exist.

**Evidence:**
- code `README.md:1620-1635` — HEAD adds the '### Opting out of source generation' section. It documents SuppressSourceGeneration and lists the diagnostics MsgPack003/004/005/012/015 as reported and MsgPack011/016/017 as not reported.
- code `README.md` — BASE README.md has no occurrence of 'SuppressSourceGeneration', so the section is new in this change.

### ✅ C13 · non-change · supported (medium, info)

**Claim:** Diagnostics and generated output for existing valid non-suppressed types are unchanged by the TypeCollector edits. _(→ F1)_

**Basis:** Direct code reading of the edited hunks in HEAD and a base grep. No tests or execution were run.

**Reasoning:** In base, the corresponding lines are unguarded `intMembers.Add` and `stringMembers.Add` calls (lines 1022, 1035, 1155, 1168). HEAD changes them only when a duplicate key or a mixed key kind exists. Both cases are invalid types that already get a diagnostic. In base, a duplicate would throw an ArgumentException on `Add`. A mixed key would reach `intKey!.Value` with a null key. A valid type with unique, consistent keys takes none of the changed paths. Its diagnostics and generated output are therefore unchanged. One side effect applies only to invalid mixed-key types: `continue` now skips the recursive `CollectCore(item.Type, item)` for the mismatched member. Diagnostics from that member's nested type can therefore be lost for such a type. This is outside the claim's scope of valid types. I did not check whether any test covers it.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1003-1010` — The new `continue` sits inside the branch where the key kind does not match. That branch already reported DoNotMixStringAndIntKeys, so it is reachable only for an invalid type with mixed keys.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1012-1043` — The `ContainsKey` guards before `Add` change behaviour only when a key is already present. In that case KeysMustBeUnique has already been reported. For unique keys the `Add` runs exactly as before.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1142-1190` — The field loop has the same two edits (the `continue` and the guarded `Add`), with the same reasoning.

### ✅ C14 · non-change · supported (medium, info)

**Claim:** The change adds no dependency or build file changes. _(→ N2)_

**Basis:** Structural comparison of base and head build files (no diff tool or shell available). The only hunks I was given are in TypeCollector.cs. I did not compare file contents byte for byte.

**Reasoning:** The shown diff touches only TypeCollector.cs, and its changes are plain C# logic. Build and dependency files have identical file sets and line counts at BASE and HEAD, so no file was added or removed and no line was added or removed in them. An in-place edit that kept the line count the same, such as a version bump, is not excluded by line counts alone. I also did not check CI workflow files or the tests projects' source files for new package references.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1002-1050` — The shown hunks only add `continue` and `ContainsKey` guards in C# member collection. They contain no package, project or build content.
- deterministic `Directory.Packages.props` — I counted lines in every csproj, props, targets, sln, global.json, packages.config and NuGet.config file in both checkouts. Both have the same 51 files and the same total of 1569 lines, with identical per-file counts. Directory.Packages.props is 81 lines in both.

## Routed to a named human

- **C7** — Run the new test class against BASE src, for example by stashing the TypeCollector.cs changes. Which tests fail? If MemberWithoutKeyIsReported and AllowPrivateRequiredIsReported pass, where is the 3.1.1 regression fixed, and how do these tests guard it?
  _Why:_ contradicted: The claim says the new tests fail without the fix and so prove the analyzer runs on suppressed types. The claim's own caveat points the other way, and the code agrees. The analyzer entry point is identical at BASE and HEAD and does not check SuppressSourceGeneration. At BASE, TypeCollector reports MsgPack004 and MsgPack015 before the suppression early return, and those paths are unchanged. So the MsgPack004 and MsgPack015 tests that N1 requires should already pass at BASE. They do not show the regression, and they do not show that the analyzer ran on a suppressed type only because of this change. Only the duplicate-key and mixed-key tests probably fail at BASE, from the unguarded Add. I found no change in the analyzer or TypeCollector entry path that affects whether suppressed types are analyzed. I did not find where HEAD differs from BASE for the 3.1.1 regression itself. I could not run anything, so the BASE pass/fail result is inferred.

## Changed files

| File | Class | +/- |
|---|---|---|
| `README.md` | docs | +14 −0 |
| `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs` | source | +18 −4 |
| `tests/MessagePack.SourceGenerator.ExecutionTests/SuppressedSourceGenerationTests.cs` | test | +37 −0 |
| `tests/MessagePack.SourceGenerator.Tests/SuppressSourceGenerationAnalyzerTests.cs` | test | +193 −0 |

---
_Sign-off: `cev decide --report <this dir> --by "Name" accept|reject` records who accepted, what they saw, and the report hash._