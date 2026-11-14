# Trust report — REQ-2297 · `origin/ju26-issue-2297`

**Recommendation: NEEDS A HUMAN — approve only after answering the routed questions**

- 1 claim(s) routed to a human: C11
- no execution evidence (tests not run here)
- requirement items only partially covered or not checkable: F1, F2, F3, N2

> The change adds a guarded [ExcludeFromCodeCoverage] attribute to the type declarations in six T4 templates (and their generated .cs). It also fixes a missing newline after a nesting-type brace, adds a README note and two new tests, and regenerates about 222 snapshot files. The guard makes the attribute apply only on targets other than netstandard2.0 and .NET Framework.

## At a glance

| | |
|---|---|
| Requirement | REQ-2297 (`requirements/REQ-2297.md`) |
| Change | `origin/HEAD` → `origin/ju26-issue-2297` (a0aa5ab2de) |
| Risk tier | **medium** — large generated/snapshot churn hides the real diff; changes code-generation templates (every consumer is affected) |
| Files | docs 1, source 7, template 6, test 1, generated 222 |
| Claims | 13: 12 supported, 0 contradicted, 1 unverifiable |
| Execution evidence | Execution evidence disabled (run with --exec to run the added tests and the mutation check). |
| Model | sonnet; cost ≈ $1.342; generated 2026-11-14T03:33:09.931Z |

## Requirement coverage

| Item | Status | Via | Note |
|---|---|---|---|
| **F1** Every type the generator emits (object formatters, string-key formatters, enum formatters,… | partial | C1, C2, C3, C4, C6 | Supported by reading: all 10 emitted types across 6 templates carry [ExcludeFromCodeCoverage] (C1-C4), and .cs matches .tt (C6, medium; T4 transform not run). But every attribute is inside '#if !NETSTANDARD2_0 && !NETFRAMEWORK', so it is absent on those targets. Requirement says 'every type'. Tests only check file-level presence (C9), not per-type. Question for human: is omission on netstandard2.0/.NET Framework acceptable for F1? |
| **F2** Generated code still compiles on every target the generator supports, including targets wh… | partial | C5, C10 | Code reading shows all attribute occurrences are guarded (C5, medium), and a text-only test confirms this within its sample (C10). No compile was run on netstandard2.0 or .NET Framework. The guard is more conservative than necessary, since the attribute exists on those targets. Question for human: should the generated code compile-check on those targets in CI? |
| **F3** Verified snapshot files are updated to match the new output, with no other differences. | partial | C7, C11 | C11 (snapshots differ only by the added lines and the brace fix) is unverifiable: only the file count and one non-nested sample were checked. C7 shows a non-requested whitespace change in TransformUtilities (brace now '{\r\n' for constrained nested types), which conflicts with 'no other differences'. Question for human: run a full diff of the ~222 snapshots and decide whether the brace change is acceptable. |
| **N1** No run-time behaviour change in serialization. | addressed | C12 | Medium confidence from reading the diff: hunks add only attributes, preprocessor lines and whitespace, and no Serialize/Deserialize or lookup code changes. No runtime or test execution evidence. |
| **N2** No unrelated dependency or build changes. | partial | C13, C8 | The csproj is unchanged, but Directory.Build.props, .targets, version.json and PublicAPI files were not compared (C13, medium). A README paragraph was added although no documentation was requested (C8, scope creep). The README says 'all' types are covered, which is broader than the guarded implementation. |

## Claims and verdicts

### ✅ C1 · behaviour · supported (high, info)

**Claim:** Object (int-key) formatter, string-key formatter, enum formatter and union formatter templates each emit [global::System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage] directly before the 'internal sealed class' declaration. _(→ F1)_

**Basis:** Direct code reading of the four templates in HEAD, using grep with context lines. I did not run the generator.

**Reasoning:** All four templates emit [global::System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage] immediately before the 'internal sealed class' line. The claim leaves out one detail. Each attribute is wrapped in '#if !NETSTANDARD2_0 && !NETFRAMEWORK', so it is omitted when the consuming project targets netstandard2.0 or .NET Framework. That wrapper appears to be the F2 compatibility handling. The claim's placement statement holds, but a reader should know the attribute is conditional.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt:14-17` — The attribute is on line 15 and the 'internal sealed class' line is 17. Only '#endif' sits between them.
- code `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.tt:18-21` — Same pattern: attribute, '#endif', then 'internal sealed class'.
- code `src/MessagePack.SourceGenerator/Transforms/EnumTemplate.tt:8-11` — Same pattern: attribute, '#endif', then 'internal sealed class'.
- code `src/MessagePack.SourceGenerator/Transforms/UnionTemplate.tt:10-13` — Same pattern: attribute, '#endif', then 'internal sealed class'.

### ✅ C2 · behaviour · supported (high, info)

**Claim:** ResolverTemplate emits the attribute on the resolver partial class and on both nested helper classes (FormatterCache<T> and <Resolver>GetFormatterHelper). _(→ F1)_

**Basis:** Direct code reading of both the .tt template and the generated .cs. No execution.

**Reasoning:** The attribute appears exactly three times in each file. Each one sits immediately before the resolver partial class, FormatterCache<T> or the GetFormatterHelper class. The claim holds. One caveat: all three are inside `#if !NETSTANDARD2_0 && !NETFRAMEWORK`, so a consumer compiling for those targets gets no attribute. The claim doesn't mention this. It matters for F1, because it narrows coverage exclusion, and F2 is probably the reason for the guard. I did not check whether the guard is needed or whether the other templates use the same one.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt:13-17` — Attribute, wrapped in #if !NETSTANDARD2_0 && !NETFRAMEWORK, placed directly before `partial class <ResolverName>`.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt:30-34` — Same guarded attribute before `private static class FormatterCache<T>`.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt:47-51` — Same guarded attribute before `private static class <ResolverName>GetFormatterHelper`.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.cs:38-67` — The generated .cs has the same three literal insertions (partial class at line 38, FormatterCache at about line 56, helper at line 67), so .tt and .cs agree.

### ✅ C3 · behaviour · supported (high, info)

**Claim:** CompositeResolverTemplate emits the attribute on the composite resolver partial class and its nested FormatterCache<T> class. _(→ F1)_

**Basis:** Direct code reading of the .tt template and its generated .cs, which agree. No execution or snapshot checks.

**Reasoning:** Both the partial resolver class and nested FormatterCache<T> get the attribute in the .tt and in the checked-in generated .cs, so the claim holds. The attribute is emitted only when the consumer doesn't define NETSTANDARD2_0 or NETFRAMEWORK. On those targets neither type gets it. This matters for F1 but is a separate question from C3 and is not tested here. Whether the emitted `#if` lines work in the generated output file is not checked.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.tt:7-10` — Attribute, guarded by #if !NETSTANDARD2_0 && !NETFRAMEWORK, placed directly before `partial class <ResolverName>`.
- code `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.tt:34-38` — Same guarded attribute placed directly before nested `static class FormatterCache<T>`.
- code `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.cs:27` — Generated TransformText writes the guarded attribute before `partial class `.
- code `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.cs:55-59` — Generated code emits the guarded attribute before `static class FormatterCache<T>`.

### ✅ C4 · behaviour · supported (high, info)

**Claim:** No type emitted by any generator template lacks the attribute (including any other emitted types or templates, e.g. nested/array/generic helper types, not touched by this diff). _(→ F1)_

**Basis:** Direct code reading of every .tt template, its generated .cs counterpart, and TransformUtilities. No execution.

**Reasoning:** I grepped all .tt files under src for class, struct, enum, interface, record and delegate declarations. There are 10 emitted type declarations across the 6 generator templates, and each has the attribute directly above it. The .cs files are in sync with the .tt files, as shown by the grep hits for ExcludeFromCodeCoverage in each generated .cs. I found no C# code that emits other types outside the templates. The only AddSource callers pass template output. Caveats: the attribute sits inside `#if !NETSTANDARD2_0 && !NETFRAMEWORK`, so on those targets no emitted type has it. That matches F2 but is a conditional reading of 'no type lacks the attribute'. The unused EmitClassesForNamespace helper would emit undecorated classes if anyone started calling it.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt:13-17` — The object formatter class is decorated. It is the only type declared in this template; the other 'struct' match is inside a string literal.
- code `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.tt:19-21` — The string-key formatter class is decorated.
- code `src/MessagePack.SourceGenerator/Transforms/UnionTemplate.tt:10-13` — The union formatter class is decorated.
- code `src/MessagePack.SourceGenerator/Transforms/EnumTemplate.tt:8-11` — The enum formatter class is decorated.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt:14-58` — All three type declarations carry the attribute: the partial resolver class (line 17), the nested FormatterCache<T> (line 34), and the nested <Name>GetFormatterHelper (line 51).
- code `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.tt:7-38` — Both type declarations carry the attribute: the partial resolver class (line 10) and the nested FormatterCache<T> (line 38).
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs:16-71` — EmitNestingTypesAndNamespaces re-declares the user's own containing types as 'partial' wrappers. These are not new generator types and are not decorated, which would be wrong anyway.
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs:93-119` — EmitClassesForNamespace emits 'partial class' wrappers without the attribute, but a repo-wide grep shows it has no callers, so it is dead code.

### ✅ C5 · behaviour · supported (medium, info)

**Claim:** Each attribute is wrapped in '#if !NETSTANDARD2_0 && !NETFRAMEWORK ... #endif', so generated code compiles for consumers targeting netstandard2.0 or .NET Framework; on those targets coverage exclusion is simply absent. _(→ F2)_

**Basis:** Direct code reading of every template containing the attribute. No compile or execution evidence. Whether consumers actually define NETSTANDARD2_0 or NETFRAMEWORK was not tested.

**Reasoning:** I grepped all .tt files for ExcludeFromCodeCoverage and NETSTANDARD2_0. The two named files hold 4 attribute occurrences, each wrapped by the same '#if' / '#endif' pair. The other templates are also guarded. On the excluded targets the attribute line is dropped, so the generated code has no reference to the attribute and coverage exclusion is simply absent. I found no unguarded occurrence. The actual compile on netstandard2.0 and .NET Framework was not run. The guard is also conservative: the attribute exists in netstandard2.0 and .NET Framework 4.0 and later, so the claim holds but the exclusion is skipped more often than it needs to be.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt:14-16` — The formatter attribute sits inside '#if !NETSTANDARD2_0 && !NETFRAMEWORK' ... '#endif', directly above the class declaration.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt:14-16` — The resolver class attribute is guarded the same way.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt:31-33` — The FormatterCache<T> attribute is guarded.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt:48-50` — The GetFormatterHelper attribute is guarded.
- code `src/MessagePack.SourceGenerator/Transforms/EnumTemplate.tt:8-10` — The same guard appears in the other templates (Enum, Union, StringKey, CompositeResolver at lines 7-9 and 35-37), so every ExcludeFromCodeCoverage occurrence in a .tt file is guarded.

### ✅ C6 · behaviour · supported (medium, info)

**Claim:** The .cs files under Transforms are edited by hand or regenerated consistently with the .tt files, so each .tt change has an identical counterpart in its .cs file. _(→ F1)_

**Basis:** Direct reading of paired .tt/.cs diffs plus a count of attribute occurrences per file; the T4 generator was not run, so byte-exact regeneration is not confirmed.

**Reasoning:** I compared each .tt hunk with its .cs hunk. Every .tt insertion has an equivalent in the .cs Write call, with the same condition, attribute text and indentation. The .cs files have no extra attribute insertions beyond the .tt ones. I could not run the T4 transform, so I cannot confirm the .cs files are byte-identical to what the generator would emit. The TransformUtilities.cs edit is outside the .tt/.cs pairing and is not what this claim is about.

**Evidence:**
- deterministic `src/MessagePack.SourceGenerator/Transforms/` — ExcludeFromCodeCoverage occurrence counts match between each .tt and its .cs: Composite 2/2, Resolver 3/3, Enum 1/1, Union 1/1, Formatter 1/1, StringKey 1/1.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.cs:32-70` — The three .tt insertions (resolver class, FormatterCache, GetFormatterHelper) each appear as the same `#if !NETSTANDARD2_0 && !NETFRAMEWORK` / attribute / `#endif` text in the Write string literals, using \r\n and the same tab indentation.
- code `src/MessagePack.SourceGenerator/Transforms/EnumTemplate.tt:5-12` — The .tt `\t[attr]` line replaces the old `\tinternal sealed class` start, and the .cs Write changes from "\r\n\tinternal…" to "\r\n#if…\r\n\t[attr]\r\n#endif\r\n\tinternal…". The Union, Formatter and StringKey .cs files follow the same pattern.
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs` — This hand-written helper has no .tt counterpart. Its `{` to `{\r\n` change applies only to nesting types with constraints, so it is not covered by this claim. It is a separate behaviour change that affects generated output.

### ✅ C7 · scope · supported (high, minor)

**Claim:** Scope: TransformUtilities.EmitNestingTypesAndNamespaces changes its opening brace output from '{' to '{\r\n' when the nesting type has type constraints; this changes generated output for nested constrained types and no requirement asks for it. _(→ F3)_

**Basis:** Direct code reading of the whole method at HEAD plus the diff hunk. No execution and no snapshot comparison.

**Reasoning:** The diff contains the change described in the claim. In the constrained case the brace now ends with a newline, so generated text for nested generic types with constraints differs. That output is whitespace only: the next emitted text now starts on a new line instead of following `{` on the same line. The requirement covers only adding ExcludeFromCodeCoverage, and F3 says snapshots should have no other differences. Neither F1, F2 nor F3 asks for a brace or line-ending change. The likely motive is that an attribute line is now emitted right after the brace, but I did not verify that. I also did not check whether any snapshot has a nested constrained type. The human decides whether this is acceptable.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs:55-59` — At HEAD the opening brace is written as `anyConstraints ? "{\r\n" : " {\r\n"`. The diff shows the base wrote `"{"` with no newline in the constrained case.
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs:73-91` — EmitTypeConstraints returns true only when a type parameter has constraints. It then writes each `where` clause ending in `\r\n`. So the changed branch applies only to nesting types that have constrained generic parameters.

### ✅ C8 · scope · supported (high, info)

**Claim:** Scope: the README gains a paragraph promising that all generated formatters and resolvers carry [ExcludeFromCodeCoverage] except on netstandard2.0 and .NET Framework. The requirements do not ask for documentation.

**Basis:** Direct reading of the README hunk and grep of all generator templates for the conditional attribute.

**Reasoning:** The diff contains the README paragraph. The requirements don't ask for documentation, so it is extra scope. Its blast radius is documentation only. The promise is implemented: six templates emit the attribute guarded by #if !NETSTANDARD2_0 && !NETFRAMEWORK. The wording 'all' is slightly broad. I did not check that every emitted type is covered, such as nested helper classes in every template. That is a code-correctness question, not a scope question.

**Evidence:**
- code `README.md:1639-1640` — Added paragraph promising [ExcludeFromCodeCoverage] on generated formatters/resolvers, except netstandard2.0 and .NET Framework.
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.cs:33` — Emits the attribute under #if !NETSTANDARD2_0 && !NETFRAMEWORK. The same guard is in the Enum, StringKey, Union, Resolver and CompositeResolver templates, so the docs match the code.
- docs  — REQ-2297 lists no documentation requirement (F1–F3, N1–N2), so the README paragraph is an unrequested addition.

### ✅ C9 · tests · supported (high, minor)

**Claim:** The new test AllGeneratedTypesAreExcludedFromCodeCoverage proves every generated file in a sample compilation contains the attribute. It checks only file-level presence with string Contains, not that each type is decorated, and not for nested helper classes, composite resolvers, or generic or constrained types. _(→ F1)_

**Basis:** Direct reading of the whole added test file. No execution, so I did not check that the test passes.

**Reasoning:** The test does check that every generated file contains the attribute string, which is the positive part of the claim. It uses file-level string Contains only, so one decorated type would satisfy a file that holds several types. The sample covers none of the cases the claim lists as missing: generic or constrained types, composite resolvers, and nested helper classes. The second test, ExcludeAttributeIsGuardedForTargetsWhereItIsUnavailable, counts attribute occurrences against guarded occurrences. It does not compare either count to the number of emitted types, so it does not close the per-type gap.

**Evidence:**
- test `tests/MessagePack.SourceGenerator.Tests/CodeCoverageExclusionTests.cs:68-80` — The test asserts at least 5 generated files. For each file it only checks `text.Contains(ExcludeAttribute)`. It does not count the attribute per type or per declaration.
- test `tests/MessagePack.SourceGenerator.Tests/CodeCoverageExclusionTests.cs:21-63` — The sample source has only a non-generic int-keyed object, a string-keyed object, an enum, a union with one member, and a `[GeneratedMessagePackResolver]` partial class. It has no generic or constrained types and no composite resolver setup. Nothing in the test targets nested helper classes.

### ✅ C10 · tests · supported (medium, info)

**Claim:** The test ExcludeAttributeIsGuardedForTargetsWhereItIsUnavailable proves every attribute occurrence is wrapped by the #if guard. It does not compile the output against netstandard2.0 or .NET Framework. _(→ F2)_

**Basis:** Direct code reading of the test and the generator templates. No execution.

**Reasoning:** The test compares the total attribute count with the wrapped count for every generated file in its sample. That supports the first half of the claim, within the sample: integer-key, string-key, enum and union formatters plus the resolver. The test is text-only, so the second half is also true. The "every" is limited to the sample source. Template variants the sample does not trigger are not covered, such as the composite resolver and generic or nested helper classes. The test also checks only that the guard string is present. It does not check that the guard condition is correct for the real targets.

**Evidence:**
- test `tests/MessagePack.SourceGenerator.Tests/CodeCoverageExclusionTests.cs:84-100` — For every generated file, counts all occurrences of the attribute and counts occurrences inside the exact `#if ...\n[\t]attr\n#endif\n` wrapper. Assert.Equal(attributeCount, guardedCount) fails if any occurrence is unwrapped. It also requires attributeCount > 0.
- test `tests/MessagePack.SourceGenerator.Tests/CodeCoverageExclusionTests.cs:103-127` — RunGeneratorAsync only runs the generator through CSharpGeneratorDriver and reads the generated text. It never emits or checks diagnostics of the output, and the references come from DefaultTargetFrameworkReferences. So nothing is compiled against netstandard2.0 or .NET Framework.
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.cs:33` — The emitted text is `#if !NETSTANDARD2_0 && !NETFRAMEWORK\r\n\t[...ExcludeFromCodeCoverage]\r\n#endif`, which matches the shape the test looks for after CRLF is normalised.

### 🟡 C11 · behaviour · unverifiable (medium, minor)

**Claim:** The roughly 222 regenerated snapshot files differ from their previous versions only by the added guarded attribute lines and the brace newline fix, with no other differences. _(→ F3)_

**Basis:** Count comparison via grep plus one side-by-side file read. No diff tool or execution was available, so the other ~221 files were not compared line by line.

**Reasoning:** The claim is that there are no other differences across 222 files. I checked the file count and one sample, and both are consistent with it. Proving the absence of any other difference needs a full diff of all 222 files, which I could not run with Read/Grep/Glob. The sample was a resolver file, not a nested-type formatter. So the brace-fix path was not checked, and nothing here would reveal an unrelated edit in another file.

**Evidence:**
- deterministic `tests/MessagePack.SourceGenerator.Tests/Resources` — Grep finds no ExcludeFromCodeCoverage in base. HEAD has 402 occurrences across 222 files. This matches the claimed ~222 count. The base directory has 225 .cs files, so about 3 files did not get the attribute.
- code `tests/MessagePack.SourceGenerator.Tests/Resources/Generics_Constraints_Multiple/MessagePack.GeneratedMessagePackResolver.g.cs:9-50` — Compared with base lines 9-41, the only changes are the added #if/[ExcludeFromCodeCoverage]/#endif blocks. This is one sampled file, and it has no nesting braces. The brace-newline fix is not exercised here.
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs` — The brace fix changes `{` to `{\r\n` when constraints are present. Snapshots with constrained nesting types should gain a newline.

**For the human:** Run `git diff --stat base..head -- tests/MessagePack.SourceGenerator.Tests/Resources` and filter out the added guarded-attribute lines and the brace newline. Is anything left? Also, which 3 of the 225 snapshot files did not change, and is that expected?

### ✅ C12 · non-change · supported (medium, info)

**Claim:** Non-change: the generated serialization and deserialization method bodies, and the formatter lookup logic, are unchanged. Only attributes, preprocessor lines and whitespace are added. _(→ N1)_

**Basis:** Direct code reading of every supplied hunk plus the full TransformUtilities.cs at HEAD. I could not run a recursive diff because Bash was unavailable, so hunks outside those supplied are unchecked.

**Reasoning:** Every hunk in Transforms/ adds attribute and `#if`/`#endif` text before a type declaration, or adds a newline in TransformUtilities. None touches Serialize/Deserialize body emission or formatter lookup. The lookup code (`GetFormatterHelper` body, `typeToKeyAndJumpMap`) appears only as unchanged context. The `.tt` and `.cs` pairs match. I found nothing in the supplied diff that changes behaviour.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs:56-59` — The only non-additive edit is `{` → `{\r\n` in the nesting-type emitter, after a constraints block. It is a whitespace change. It puts the next `#if` line at the start of a line. No logic changes.
- code `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.cs` — Added strings are only `#if !NETSTANDARD2_0 && !NETFRAMEWORK`, `[ExcludeFromCodeCoverage]` and `#endif`, placed before the class declarations (resolver, FormatterCache, GetFormatterHelper). The `GetFormatter`/`FormatterCache` bodies in the hunks are unchanged.
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.cs` — Same pattern before `internal sealed class`. Serialize/Deserialize emission is not in any hunk. The same holds for the String-key, Enum, Union and CompositeResolver templates. Each `.cs` change mirrors the matching `.tt` change.

### ✅ C13 · non-change · supported (medium, info)

**Claim:** Non-change: no csproj, package reference, build props or public API files are modified. _(→ N2)_

**Basis:** Direct code reading of both csproj files plus the supplied diff hunks. No git diff or execution was available, so the other build files were not compared line by line.

**Reasoning:** I read the csproj in both checkouts and found no difference. The hunks given for this claim cover only Transforms/*.tt, the matching generated .cs files and TransformUtilities.cs. I did not compare Directory.Build.props, the .targets file, version.json or any PublicAPI files, so I cannot rule out a change there. There are also no files outside src/MessagePack.SourceGenerator/ in what I was given.

**Evidence:**
- code `src/MessagePack.SourceGenerator/MessagePack.SourceGenerator.csproj:1-103` — HEAD and BASE csproj are identical line by line, including the three PackageReference entries at lines 93-95.
- code `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs` — The only non-template source change is a '\r\n' added after '{' in nesting-type emission. This is a code change, not a build, package or API file.
- code `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.tt` — All other hunks are .tt/.cs template edits that add the #if-guarded ExcludeFromCodeCoverage attribute. No csproj, props or PublicAPI file appears in the provided diff.

## Routed to a named human

- **C11** — Run `git diff --stat base..head -- tests/MessagePack.SourceGenerator.Tests/Resources` and filter out the added guarded-attribute lines and the brace newline. Is anything left? Also, which 3 of the 225 snapshot files did not change, and is that expected?
  _Why:_ unverifiable: The claim is that there are no other differences across 222 files. I checked the file count and one sample, and both are consistent with it. Proving the absence of any other difference needs a full diff of all 222 files, which I could not run with Read/Grep/Glob. The sample was a resolver file, not a nested-type formatter. So the brace-fix path was not checked, and nothing here would reveal an unrelated edit in another file.

## Changed files

| File | Class | +/- |
|---|---|---|
| `README.md` | docs | +3 −0 |
| `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.cs` | source | +4 −1 |
| `src/MessagePack.SourceGenerator/Transforms/CompositeResolverTemplate.tt` | template | +6 −0 |
| `src/MessagePack.SourceGenerator/Transforms/EnumTemplate.cs` | source | +1 −1 |
| `src/MessagePack.SourceGenerator/Transforms/EnumTemplate.tt` | template | +3 −0 |
| `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.cs` | source | +1 −1 |
| `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt` | template | +3 −0 |
| `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.cs` | source | +5 −2 |
| `src/MessagePack.SourceGenerator/Transforms/ResolverTemplate.tt` | template | +9 −0 |
| `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.cs` | source | +1 −1 |
| `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.tt` | template | +3 −0 |
| `src/MessagePack.SourceGenerator/Transforms/TransformUtilities.cs` | source | +1 −1 |
| `src/MessagePack.SourceGenerator/Transforms/UnionTemplate.cs` | source | +1 −1 |
| `src/MessagePack.SourceGenerator/Transforms/UnionTemplate.tt` | template | +3 −0 |
| `tests/MessagePack.SourceGenerator.Tests/CodeCoverageExclusionTests.cs` | test | +130 −0 |
| _222 generated/snapshot files_ | generated | |

---
_Sign-off: `cev decide --report <this dir> --by "Name" accept|reject` records who accepted, what they saw, and the report hash._