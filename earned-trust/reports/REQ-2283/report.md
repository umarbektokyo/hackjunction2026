# Trust report — REQ-2283 · `origin/ju26-issue-2283`

**Recommendation: NEEDS A HUMAN — approve only after answering the routed questions**

- 3 minor claim(s) contradicted (wording or docs, not behaviour): C4, C9, C12
- 1 claim(s) routed to a human: C10
- no execution evidence (tests not run here)
- requirement items only partially covered or not checkable: F3, F4, N1, N3

> The change stops TypeCollector from indexing empty DeclaringSyntaxReferences for metadata-only symbols, using FirstOrDefault for the property and member-needs-key diagnostics. It also wraps the analyzer diagnostic callback so any diagnostic not located in the compilation's own syntax trees is silently dropped. It adds three metadata-reference tests and two docs notes.

## At a glance

| | |
|---|---|
| Requirement | REQ-2283 (`requirements/REQ-2283.md`) |
| Change | `origin/HEAD` → `origin/ju26-issue-2283` (9df83c3840) |
| Risk tier | **low** — no flags |
| Files | docs 2, source 1, test 1 |
| Claims | 13: 9 supported, 3 contradicted, 1 unverifiable |
| Execution evidence | Execution evidence disabled (run with --exec to run the added tests and the mutation check). |
| Model | sonnet; cost ≈ $1.583; generated 2026-11-14T03:29:05.710Z |

## Requirement coverage

| Item | Status | Via | Note |
|---|---|---|---|
| **F1** Building a project that references a generic value type with `[MessagePackObject]` from an… | addressed | C1, C2, C3 | Both DeclaringSyntaxReferences[0] crash sites replaced with null-safe access (C1, C2); C3 (medium) supports no CS8785/AD0001 via code reading. Not executed; tests' fail-on-base unverified (C10). |
| **F2** The generated resolver for the consuming project is still produced in that situation. | addressed | C3, C8 | C3 (medium, code reading) and C8 (test asserts resolver hint name) support resolver still emitted. No execution evidence; human should run the new tests. |
| **F3** The trigger matrix from the report is covered: generic + value type + referenced assembly … | partial | C8, C9 | Crashing cases (generic struct, record struct) are tested (C8). The non-crashing controls (non-generic struct, generic class from referenced assembly) have no test (C9 contradicted), so the full trigger matrix is not covered. |
| **F4** Existing diagnostics for types declared in the compilation being analysed keep their curre… | partial | C6, C7, C4, C12 | Source-symbol locations are unchanged and still reported (C6, C7, medium, code reading only). But the global filter drops diagnostics with no location or from other compilations (C5), C4 shows the filter is inconsistently applied (InaccessibleDataType bypasses it), and C12's doc claim is contradicted. Behaviour for source-declared types holds, but the filter's scope goes beyond the requirement. |
| **N1** No behaviour change for types declared in source (regression tests must still pass). | partial | C6, C5 | C6 supports unchanged source behaviour by reading, but the existing tests were not run. C5 shows the diagnostic filter is a broader behaviour change; record positional property previously threw and is now silently dropped (C6). |
| **N2** The fix is in the analyzer/generator (`MessagePack.SourceGenerator`), not a workaround in … | addressed | C1, C2 | Fix is in TypeCollector.cs of MessagePack.SourceGenerator, not user-code workaround. |
| **N3** The change is small and reviewable; no unrelated dependency or build changes. | partial | C5, C13 | Change adds unrequested docs, a new helper, and a global diagnostic filter wrapper (C5, C13). No dependency, build or public API changes seen, but the full diff was not checked. Whether the filter's blast radius is acceptable is a human decision. |

## Claims and verdicts

### ✅ C1 · behaviour · supported (high, info)

**Claim:** The BothStringAndIntKeyAreNull diagnostic no longer indexes DeclaringSyntaxReferences[0]; it uses GetPropertyIdentifierLocation, which returns null for metadata properties instead of throwing IndexOutOfRangeException. _(→ F1, N2)_

**Basis:** Direct code reading of the call site and the helper in HEAD. No execution or test evidence.

**Reasoning:** I grepped HEAD for `DeclaringSyntaxReferences[0]` and for the helper. The BothStringAndIntKeyAreNull call site calls the helper, and the helper uses FirstOrDefault, so the empty collection of a metadata property gives null. `Diagnostic.Create` accepts a null location. I did not read the declaration of `item` near line 985, but the helper's IPropertySymbol parameter type and the compile-time use of `item.GetMethod` there show it is a property symbol. The hunk also adds ReportIfLocatedInCompilation, which drops diagnostics with no source location. That is related to the claim but not part of it.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:983-986` — The BothStringAndIntKeyAreNull diagnostic now takes its location from GetPropertyIdentifierLocation(item). The DeclaringSyntaxReferences[0] indexing is gone.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1434` — The helper uses DeclaringSyntaxReferences.FirstOrDefault()?.GetSyntax() as PropertyDeclarationSyntax. For a metadata property the collection is empty, so it returns null instead of throwing IndexOutOfRangeException.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:715` — The only other `DeclaringSyntaxReferences[0]` left in the file is in a commented-out line, so it is not a live path.

### ✅ C2 · behaviour · supported (high, info)

**Claim:** The MemberNeedsKey diagnostic now uses DeclaringSyntaxReferences.FirstOrDefault()?.GetSyntax().GetLocation(), so a metadata member yields a null location instead of throwing. _(→ F1, N2)_

**Basis:** Direct code reading of the changed line, its surrounding branch, and the reportDiagnostic wrapper. Not executed.

**Reasoning:** The claim says one line uses FirstOrDefault()?.GetSyntax().GetLocation() and so yields a null location instead of throwing. Line 1077 matches that exactly, and no other indexer remains on this path (the only remaining [0] is in a commented-out line at 715). The claim is narrow, so the extra filtering wrapper does not contradict it. That wrapper is out of this claim's scope. The diff also adds a GetPropertyIdentifierLocation helper and a filtering wrapper that were not part of the claim. I did not execute any code.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1077` — MemberNeedsKey now uses item.DeclaringSyntaxReferences.FirstOrDefault()?.GetSyntax().GetLocation(). For a metadata member the collection is empty, so FirstOrDefault returns null and the whole expression is null. The old [0] indexer threw IndexOutOfRangeException.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1075-1085` — Diagnostic.Create accepts a null Location (it becomes Location.None). The diagnostic is then reported or deferred without dereferencing the location.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1` — The constructor wraps reportDiagnostic in ReportIfLocatedInCompilation. A null or non-source location is dropped silently. So the null location does not reach the analyzer, which also matches F4.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:930` — The other MemberNeedsKey site uses identifier?.GetLocation(), which was already null-safe.

### ✅ C3 · behaviour · supported (medium, info)

**Claim:** With these fixes, a [MessagePackObject] class with a member of closed generic struct type from a referenced assembly (including a record struct) builds with no CS8785/AD0001 and still emits the resolver (e.g. TempProject.MyResolver.g.cs). _(→ F1, F2)_

**Basis:** Code reading of the full diagnostic path in TypeCollector plus inspection of the added tests. No execution, so the tests were not run.

**Reasoning:** In BASE, the two [0] indexers throw for metadata symbols, which gives AD0001 and CS8785. In HEAD, I read every reportDiagnostic call site and the remaining DeclaringSyntaxReferences usages. None of them can throw for empty syntax references, and the wrapper suppresses locations outside the compilation. The record-struct and generic-struct cases both reach the same member-processing code. The added tests would fail if the crash remained, because the analyzer verifier fails on AD0001 and the generator run asserts the resolver hint name. I could not find a different crash source for record structs, but I did not run the tests. Other metadata-only quirks of record structs are therefore unobserved.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:236-239` — The analyzer callback is wrapped in ReportIfLocatedInCompilation. Diagnostics with no source location in this compilation are dropped, so nothing is reported at a metadata location.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:985` — The BothStringAndIntKeyAreNull path no longer indexes DeclaringSyntaxReferences[0]. It now uses GetPropertyIdentifierLocation, which uses FirstOrDefault and a null-safe cast.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1078` — The MemberNeedsKey path was the second [0] indexer. It now uses FirstOrDefault()?.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1438-1452` — The helper ReportIfLocatedInCompilation checks Location.IsInSource and compilation.ContainsSyntaxTree before reporting. A null location becomes Location.None and is filtered out.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:943` — A grep for remaining DeclaringSyntaxReferences[0], First() and Single() in src/MessagePack.SourceGenerator found none besides commented-out code. The SelectMany uses at 943 and 1090 are safe on empty collections. Locations[0] at 1341 is non-empty for metadata symbols.
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:47` — The generator passes reportAnalyzerDiagnostic: null. Its only crash source was the [0] indexing in the diagnostic arguments, which is now fixed, so resolver generation is not interrupted.
- test `tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs:496-680` — The tests ClosedGenericStruct_FromMetadataReference, ClosedGenericRecordStruct_FromMetadataReference and the UnkeyedMember variant compile the defining project to an image and reference it as metadata only. They run the analyzers and generator with SkipGeneratedSourcesCheck. Then they assert no warnings or errors from the generator run and that the hint name (e.g. TempProject.MyResolver.g.cs) is present.

### ❌ C4 · behaviour · contradicted (high, minor)

**Claim:** Every analyzer diagnostic reported through TypeCollector's reportDiagnostic callback is now filtered. It is forwarded only if its location is in source and its syntax tree belongs to the current compilation. All other diagnostics are dropped silently. _(→ F4, N1)_

**Basis:** Direct code reading of the constructor and every reportDiagnostic call site in TypeCollector.cs. No execution.

**Reasoning:** The claim says every diagnostic reported through the callback is filtered. The filter does cover the this.reportDiagnostic field, and that is the path nearly all diagnostics use. The InaccessibleDataType diagnostic at line 248 goes to the original callback directly and is never filtered. Its location comes from FindInaccessibleTypes declarations. I did not check whether those can be outside the compilation. The wording 'every' is therefore literally false, although the practical impact may be small.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:239` — The this.reportDiagnostic field is wrapped with ReportIfLocatedInCompilation, so everything sent through the field is filtered.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:248` — The constructor calls the raw reportAnalyzerDiagnostic parameter for InaccessibleDataType. This bypasses the filter, so not every diagnostic is filtered.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1436-1446` — The filter forwards a diagnostic only if Location.IsInSource and compilation.ContainsSyntaxTree(SourceTree). This matches the 'in source and in compilation' part of the claim.

### ✅ C5 · scope · supported (medium, minor)

**Claim:** The global diagnostic filter is a broader change than the crash fix needs. Diagnostics with Location.None or a location in a different compilation that were previously reported (e.g. null-location MemberNeedsKey, or diagnostics for in-source types located via other trees) are now suppressed. _(→ F4, N1, N3)_

**Basis:** Direct code reading of the constructor wrapper, the filter method, and the call sites. No execution or test evidence.

**Reasoning:** The diff wraps the single reportDiagnostic delegate, so the filter applies to every diagnostic path. That is wider than the crash fix, which needed only the three DeclaringSyntaxReferences[0] sites replaced. Null-location diagnostics, and any diagnostic whose tree is not in this compilation, are now dropped. One part of the claim's wording is inaccurate. Diagnostics for in-source types located via other trees of the same compilation still pass, because ContainsSyntaxTree is true for them. Only trees from a different compilation, or no location at all, are suppressed. F4 and N1 appear to hold for source-declared types, since source locations are unchanged. The example of a null-location MemberNeedsKey is plausible only for metadata members. For metadata members the old code crashed on [0], so no diagnostic was ever reported there.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:239` — The constructor wraps the analyzer's report callback, so every this.reportDiagnostic call goes through the filter, not only the crash sites.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1444-1450` — The filter forwards a diagnostic only if Location.IsInSource and compilation.ContainsSyntaxTree(tree). Location.None and metadata locations are dropped silently.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:397` — UnionAttributeRequired already used FirstOrDefault()?.GetLocation() in base. For a metadata type it passes a null location, which was reported at Location.None before and is now dropped.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1007-1161` — Many other sites use FirstOrDefault()?.GetSyntax().GetLocation(), which can be null. All are now filtered.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:248` — InaccessibleDataType is raised through the raw reportAnalyzerDiagnostic, so it bypasses the filter. The filter is not fully global.

### ✅ C6 · non-change · supported (medium, minor)

**Claim:** Diagnostics for types and members declared in the compilation being analysed keep the same locations and are still reported, so existing analyzer tests pass unchanged. _(→ F4, N1)_

**Basis:** Direct code reading of the diff and the report paths in TypeCollector.cs and its two callers. I did not run any tests, so "existing tests pass unchanged" is inferred from the code, not observed.

**Reasoning:** I read every this.reportDiagnostic call site in TypeCollector.cs. For types and members declared in the analysed compilation, the location arguments are unchanged apart from the DeclaringSyntaxReferences[0] to FirstOrDefault() swaps and the helper at line 985. Those give the same location for source symbols. The new filter drops only diagnostics whose location is not a source location in this compilation. That means metadata symbols, such as the Locations[0] at line 1341 for a referenced type, and null locations. Two behaviour changes sit outside the claim. A record positional property, where the declaring syntax is a ParameterSyntax, used to throw InvalidCastException at line 985 and now gets a null location and is silently dropped. Diagnostics for metadata types are also now dropped instead of being reported. I did not run the analyzer tests, so the "pass unchanged" part rests on code reading alone.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:236-239` — The diagnostic sink is wrapped in a filter. It forwards only diagnostics that are in source and whose tree is in this.compilation. Locations of source-declared types and members satisfy that, so they are forwarded unchanged. The InaccessibleDataType report at line 248 uses the raw sink and is unaffected.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1427-1451` — GetPropertyIdentifierLocation returns the same Identifier.GetLocation() as the old cast for a PropertyDeclarationSyntax. ReportIfLocatedInCompilation only filters and does not change locations.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1076-1077` — DeclaringSyntaxReferences[0] became FirstOrDefault()?. For a source member the first element is the same, so the location is identical.
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:430` — The analyzer passes context.Compilation and context.ReportDiagnostic, so source trees belong to that compilation. The generator passes a null reporter (MessagePackGenerator.cs:47), so no filter is created there.

### ✅ C7 · non-change · supported (medium, info)

**Claim:** The BothStringAndIntKeyAreNull location for source properties is unchanged. GetPropertyIdentifierLocation uses 'as PropertyDeclarationSyntax' where the old code used a hard cast, which returns null instead of throwing for a non-property declaration. _(→ F4, N1)_

**Basis:** Direct code reading of the base and HEAD call sites, the new helper, and the reporting wrapper. Nothing was executed and no test was checked.

**Reasoning:** For a property declared in source, the declaration is a PropertyDeclarationSyntax. The new `as` cast and the old hard cast therefore both yield the same Identifier.GetLocation(), and the diagnostic descriptor and message arguments are identical. The code at line 888 handles indexers with `item.IsIndexer`; I did not read what it does, so I cannot rule out an indexer reaching line 985. The new wrapper can only suppress diagnostics located outside the compilation, which the base code would have crashed on, so it does not alter source locations. The claim's note about `as` returning null instead of throwing is also accurate. A separate site at line 1128 uses FirstOrDefault and is untouched. One caveat is that a null location is now silently dropped by the wrapper rather than reported with no location. That is part of the fix, not a change to source property locations.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:985` — HEAD: the BothStringAndIntKeyAreNull call site now passes GetPropertyIdentifierLocation(item) as the location. Message arguments are unchanged.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1434` — HEAD: the helper uses FirstOrDefault()?.GetSyntax() as PropertyDeclarationSyntax, then ?.Identifier.GetLocation(). For a source property this is the same identifier location as before; for a missing or non-property declaration it returns null instead of throwing.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:985` — BASE: the old code was ((PropertyDeclarationSyntax)item.DeclaringSyntaxReferences[0].GetSyntax()).Identifier.GetLocation(). That throws on an empty collection (IndexOutOfRange) and a hard cast throws InvalidCastException on a non-property node.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:239` — HEAD: the reporter is now wrapped by ReportIfLocatedInCompilation (defined at line 1444). It drops diagnostics whose location is not in a source tree of this compilation. Source-declared properties still pass, so their reported location is unchanged.

### ✅ C8 · tests · supported (medium, info)

**Claim:** The new tests ClosedGenericStruct_FromMetadataReference, ClosedGenericRecordStruct_FromMetadataReference and ClosedGenericStruct_FromMetadataReference_UnkeyedMember each compile the defining source to a metadata-only image and fail on any analyzer/generator diagnostic. They also assert that the expected resolver hint name is generated. _(→ F1, F2, F3)_

**Basis:** Direct code reading of the three tests, the shared helper and the test verifier base class. No execution, so I did not confirm the tests pass.

**Reasoning:** Each test meets both parts of the claim. The first run, through the analyzer/generator test harness, fails on any diagnostic. The second run drives the generator directly and asserts the resolver hint name is present. The defining assembly is a compiled image referenced as metadata, so no syntax is available to the consumer. Two details do not weaken the claim. First, the first run uses SkipGeneratedSourcesCheck, so the hint-name assertion comes only from the separate driver run. Second, the image is a full in-memory assembly, not a reference assembly. I did not verify that the tests fail on BASE.

**Evidence:**
- test `tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs:500-690` — The three tests each call RunWithMetadataReferenceAsync with their own define/usage source and expected hint name: TempProject.MyResolver.g.cs, App.AppResolver.g.cs, TempProject.MyResolver.g.cs.
- test `tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs:626-666` — The helper compiles the defining source with Emit into a MemoryStream and loads it with MetadataReference.CreateFromImage, so the consumer sees no syntax. It then runs VerifyCS.Test with no ExpectedDiagnostics, so any diagnostic fails the run. It then runs the generator driver, asserts no warning-or-worse diagnostics, and asserts the hint-name list contains the expected resolver name.
- code `tests/MessagePack.SourceGenerator.Tests/Verifiers/CSharpSourceGeneratorVerifier`1+Test.cs:33-172` — The Test sets CompilerDiagnostics.Warnings and runs every DiagnosticAnalyzer in the analyzer assembly plus the generator. CS8785 and AD0001 are warnings, so they would fail the run.
- code `src/MessagePack.SourceGenerator/Transforms/TemplatePartials.cs:64` — The resolver file name is the namespace-qualified resolver name plus .g.cs, which matches the hint names the tests assert.

### ❌ C9 · tests · contradicted (high, minor)

**Claim:** The new tests cover the report's trigger matrix, including the non-crashing controls (non-generic struct and generic class from a referenced assembly). They cover only generic structs and a record struct. _(→ F3)_

**Basis:** Direct code reading of all new tests in the file, plus a grep for other callers of the new helper.

**Reasoning:** The claim's first sentence says the tests include the non-crashing controls: a non-generic struct and a generic class from a referenced assembly. I found no such test. The only new tests use a generic struct, a generic record struct, or a generic struct with an unkeyed member. The claim's second sentence ("only generic structs and a record struct") matches the code, but it contradicts the first sentence. The requirement F3 asks for the full trigger matrix, so the controls are missing. The positive-crash cases are covered, and the negative controls are not.

**Evidence:**
- test `tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs:507-625` — The only three new tests are ClosedGenericStruct_FromMetadataReference, ClosedGenericRecordStruct_FromMetadataReference and ClosedGenericStruct_FromMetadataReference_UnkeyedMember. All define a generic struct or record struct in the referenced assembly.
- test `tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs:633` — RunWithMetadataReferenceAsync is called only by those three tests (grep). Nothing passes a non-generic struct or a generic class as the referenced type.

### 🟡 C10 · tests · unverifiable (medium, minor)

**Claim:** The new tests fail on the pre-fix code (they reproduce the AD0001/CS8785 crash), and the UnkeyedMember test exercises the MemberNeedsKey path. _(→ F1, F3)_

**Basis:** Code reading of base and head TypeCollector.cs against the three added tests. No execution evidence. One Roslyn runtime behaviour is assumed from memory, not observed.

**Reasoning:** The tests do use metadata-only references, a closed generic struct, and an unkeyed member, so they plausibly hit the crash. The only base crash site reachable with [Key(0)] properties is the field loop at line 1077, through auto-property backing fields. That depends on a PE-loaded backing field having IsImplicitlyDeclared == false, which I recalled from Roslyn and did not observe. If so, all three tests would fail on base, and the UnkeyedMember test would also reach MemberNeedsKey through its Unkeyed property, which the HEAD location filter drops. The 'fails on pre-fix code' half rests on that unobserved behaviour. The 'UnkeyedMember exercises MemberNeedsKey' half holds by code reading, but the extra Unkeyed property does not reach the crashing line 1077. Only the backing fields do, and the other two tests have them too. I did not verify whether the test hosts' analyzers report AD0001 for the base throw.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:985` — BASE: the BothStringAndIntKeyAreNull path indexes DeclaringSyntaxReferences[0]. It only runs when a key attribute has neither an int nor a string value. All three tests use [Key(0)], so none of them reach it.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1062-1077` — BASE: in the IFieldSymbol loop, an unkeyed non-static field whose IsImplicitlyDeclared is false reaches MemberNeedsKey with DeclaringSyntaxReferences[0]. For a metadata type that is empty, so it throws. HEAD uses FirstOrDefault()?. This is the only MemberNeedsKey site that crashes on base.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:913-930` — The property-loop MemberNeedsKey path already used FirstOrDefault() on base (same code on HEAD). The Unkeyed property in the UnkeyedMember test cannot crash there on base. It only yields a diagnostic with a null location.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1444-1450` — HEAD only: ReportIfLocatedInCompilation drops diagnostics whose location is not in the compilation. The UnkeyedMember test therefore exercises the MemberNeedsKey path on HEAD, because the Unkeyed property (MemberNeedsKey, null location) is dropped there.
- test `tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs:499-690` — The three tests compile the defining assembly to an image and reference it as metadata. They run the verifier with no expected diagnostics, then assert the resolver hint name is generated. They contain no field members, so any failure on base would come from compiler-generated backing fields.

**For the human:** Run the three new tests on the BASE checkout (git stash the src fix only). Do ClosedGenericStruct_FromMetadataReference, ClosedGenericRecordStruct_FromMetadataReference and ClosedGenericStruct_FromMetadataReference_UnkeyedMember each fail with AD0001/CS8785 (IndexOutOfRangeException at TypeCollector.cs:1077)? Also confirm that the Unkeyed test's crash comes from the compiler-generated backing fields, not from the Unkeyed property, which base already handled safely at line 930.

### ✅ C11 · docs · supported (medium, info)

**Claim:** README.md adds a 'Generic types from referenced assemblies' section promising that closed generic types, including generic value types and record structs, from referenced assemblies work as members. It also says diagnostics about their members are reported by the defining assembly. _(→ F1)_

**Basis:** Direct code reading of the diagnostic reporting path in TypeCollector.cs at HEAD, compared with BASE. I did not run tests or look for a test of the referenced-assembly scenario.

**Reasoning:** BASE crashed because it indexed DeclaringSyntaxReferences[0] at TypeCollector.cs:985 and :1077, and metadata symbols have no syntax references. HEAD makes both accesses null-safe and drops any diagnostic that has no location in the current compilation. So the consuming project no longer reports problems in members of a referenced type. This matches the README sentence that diagnostics are reported by the defining assembly rather than the consumer. The wording is slightly loose. The consumer drops these diagnostics, and the defining assembly reports them only if the analyzer runs there. I read the whole path only for the diagnostic side. The promise that closed generic value types and record structs work as members rests on the removed indexers. I did not trace that to the generated code or to a test.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:985` — HEAD uses the null-safe GetPropertyIdentifierLocation. BASE used DeclaringSyntaxReferences[0], which throws for metadata symbols.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1077` — HEAD uses DeclaringSyntaxReferences.FirstOrDefault()?. BASE used the [0] indexer.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:239` — The reportDiagnostic callback is wrapped in ReportIfLocatedInCompilation.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1436-1450` — ReportIfLocatedInCompilation drops diagnostics whose location is not in a syntax tree of the current compilation. Its remarks say that problems in metadata types are reported by the compilation that defines them.

### ❌ C12 · docs · contradicted (medium, minor)

**Claim:** doc/analyzers/MsgPack004.md now states that the analyzer reports only on members declared in the project being compiled, and that unattributed members of referenced types are reported by the defining project. This generalises beyond MsgPack004 and beyond the changed paths, since the filter applies to all diagnostics. _(→ F4)_

**Basis:** Direct code reading of the diagnostic filter and both MsgPack004 report paths in TypeCollector.cs. Nothing was executed and no test was read.

**Reasoning:** The doc text exists and is accurate for members declared directly on a metadata type. Those diagnostics have no source location, so the filter drops them. The filter also covers all diagnostics, as the claim says. The doc statement is too absolute, though. When a source type derives from a referenced base type with unattributed public members, MsgPack004 is still reported in the consuming project, at the base-type reference. That contradicts "only reports on members declared in the project" and "must be fixed in its defining project". The consumer can fix it locally, for example by changing the base type or ignoring the member. I did not check whether the defining project actually runs the analyzer. I also did not verify how the doc's wording was chosen against F4.

**Evidence:**
- docs `doc/analyzers/MsgPack004.md:49-52` — The doc says the analyzer reports only on members declared in the compiled project. It also says an unattributed public member of a referenced type must be fixed in its defining project.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:239` — All analyzer diagnostics go through ReportIfLocatedInCompilation, so the filter does apply to every diagnostic, not just MsgPack004. This supports the generalisation part of the claim.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1444-1450` — The filter keeps a diagnostic only if its location is in source and in a syntax tree of this compilation. It judges the diagnostic's location, not whether the member was declared in the project.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:940-953` — When a source type inherits unattributed public members from a base type in a referenced assembly, MsgPack004 (BaseTypeContainsUnattributedPublicMembers) is reported at the base-type clause in the consuming project. The filter lets it through because that location is in source. The same pattern appears at lines 1087-1095.
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:75-77` — BaseTypeContainsUnattributedPublicMembers uses the MsgPack004 ID (AttributeMessagePackObjectMembersId), so this case falls under the doc page.

**For the human:** Should the doc mention that inherited unattributed members from a referenced base type are still reported as MsgPack004 at the base-type clause in the consuming project? If not, is the absolute wording intended?

### ✅ C13 · scope · supported (medium, minor)

**Claim:** Documentation additions and the new private helper methods (GetPropertyIdentifierLocation, ReportIfLocatedInCompilation) are not requested by any requirement item. No dependencies, build files or public API change. _(→ N3)_

**Basis:** Direct code reading of the hunks and a grep of HEAD and BASE. I did not see the full diff, so build and dependency files are unchecked.

**Reasoning:** The diff contains the docs and both helpers. The requirement document asks only for the crash fix (replace DeclaringSyntaxReferences[0] with FirstOrDefault-style access), plus F4/N1 (no behaviour change for in-source types) and N3 (small change). It asks for neither docs nor a diagnostic-filtering wrapper. The helpers are private and the constructor is private, so there is no public API change. The hunks I saw touch no dependency or build files; I did not check the full diff for any. Blast radius: ReportIfLocatedInCompilation applies to every diagnostic reported through TypeCollector, not just the crash paths. The human should decide whether that is acceptable, because it goes beyond a minimal fix.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:1430-1453` — HEAD adds two private helpers: a static GetPropertyIdentifierLocation and an instance ReportIfLocatedInCompilation. Both are private, so there is no public API change. BASE has zero matches for either name.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs:239` — The private constructor wraps reportAnalyzerDiagnostic in ReportIfLocatedInCompilation. This drops every diagnostic whose location is not in the compilation. Requirements F4/N1 only say that in-source diagnostics keep being reported; nothing asks for a general filter.
- code `README.md:1636-1646` — New README section 'Generic types from referenced assemblies'. No requirement item asks for documentation.
- code `doc/analyzers/MsgPack004.md:44-52` — New section 'Types from referenced assemblies' in the MsgPack004 doc. No requirement item asks for it.

## Routed to a named human

- **C4** — Evidence contradicts C4. Decide whether the change is still acceptable and record why.
  _Why:_ contradicted: The claim says every diagnostic reported through the callback is filtered. The filter does cover the this.reportDiagnostic field, and that is the path nearly all diagnostics use. The InaccessibleDataType diagnostic at line 248 goes to the original callback directly and is never filtered. Its location comes from FindInaccessibleTypes declarations. I did not check whether those can be outside the compilation. The wording 'every' is therefore literally false, although the practical impact may be small.
- **C9** — Evidence contradicts C9. Decide whether the change is still acceptable and record why.
  _Why:_ contradicted: The claim's first sentence says the tests include the non-crashing controls: a non-generic struct and a generic class from a referenced assembly. I found no such test. The only new tests use a generic struct, a generic record struct, or a generic struct with an unkeyed member. The claim's second sentence ("only generic structs and a record struct") matches the code, but it contradicts the first sentence. The requirement F3 asks for the full trigger matrix, so the controls are missing. The positive-crash cases are covered, and the negative controls are not.
- **C10** — Run the three new tests on the BASE checkout (git stash the src fix only). Do ClosedGenericStruct_FromMetadataReference, ClosedGenericRecordStruct_FromMetadataReference and ClosedGenericStruct_FromMetadataReference_UnkeyedMember each fail with AD0001/CS8785 (IndexOutOfRangeException at TypeCollector.cs:1077)? Also confirm that the Unkeyed test's crash comes from the compiler-generated backing fields, not from the Unkeyed property, which base already handled safely at line 930.
  _Why:_ unverifiable: The tests do use metadata-only references, a closed generic struct, and an unkeyed member, so they plausibly hit the crash. The only base crash site reachable with [Key(0)] properties is the field loop at line 1077, through auto-property backing fields. That depends on a PE-loaded backing field having IsImplicitlyDeclared == false, which I recalled from Roslyn and did not observe. If so, all three tests would fail on base, and the UnkeyedMember test would also reach MemberNeedsKey through its Unkeyed property, which the HEAD location filter drops. The 'fails on pre-fix code' half rests on that unobserved behaviour. The 'UnkeyedMember exercises MemberNeedsKey' half holds by code reading, but the extra Unkeyed property does not reach the crashing line 1077. Only the backing fields do, and the other two tests have them too. I did not verify whether the test hosts' analyzers report AD0001 for the base throw.
- **C12** — Should the doc mention that inherited unattributed members from a referenced base type are still reported as MsgPack004 at the base-type clause in the consuming project? If not, is the absolute wording intended?
  _Why:_ contradicted: The doc text exists and is accurate for members declared directly on a metadata type. Those diagnostics have no source location, so the filter drops them. The filter also covers all diagnostics, as the claim says. The doc statement is too absolute, though. When a source type derives from a referenced base type with unattributed public members, MsgPack004 is still reported in the consuming project, at the base-type reference. That contradicts "only reports on members declared in the project" and "must be fixed in its defining project". The consumer can fix it locally, for example by changing the base type or ignoring the member. I did not check whether the defining project actually runs the analyzer. I also did not verify how the doc's wording was chosen against F4.

## Changed files

| File | Class | +/- |
|---|---|---|
| `README.md` | docs | +5 −0 |
| `doc/analyzers/MsgPack004.md` | docs | +5 −0 |
| `src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs` | source | +26 −3 |
| `tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs` | test | +189 −0 |

---
_Sign-off: `cev decide --report <this dir> --by "Name" accept|reject` records who accepted, what they saw, and the report hash._