# Trust report — REQ-2129 · `origin/ju26-issue-2129`

**Recommendation: NEEDS A HUMAN — approve only after answering the routed questions**

- no execution evidence (tests not run here)
- high risk tier requires a human on every unverifiable item
- requirement items only partially covered or not checkable: F1, F4, N3

> Adds a [GeneratedMessagePackFormatter] attribute (with optional SurrogateType) so the source generator fills in a user-declared partial IMessagePackFormatter<T> class for a type from another assembly, using contractless mode or surrogate-declared keys. Adds four analyzer diagnostics (MsgPack019-022), modifies the two formatter templates to emit "partial class", excludes these formatters from hand-written-formatter registration, and adds docs and tests.

## At a glance

| | |
|---|---|
| Requirement | REQ-2129 (`requirements/REQ-2129.md`) |
| Change | `origin/HEAD` → `origin/ju26-issue-2129` (083afd994c) |
| Risk tier | **high** — 456 changed source/template lines; touches public API surface (annotations/attributes); changes code-generation templates (every consumer is affected) |
| Files | docs 7, source 10, template 2, test 6, build 3 |
| Claims | 14: 14 supported, 0 contradicted, 0 unverifiable |
| Execution evidence | Execution evidence disabled (run with --exec to run the added tests and the mutation check). |
| Model | sonnet; cost ≈ $1.6; generated 2026-11-14T03:34:11.438Z |

## Requirement coverage

| Item | Status | Via | Note |
|---|---|---|---|
| **F1** A new attribute, e.g. `[GeneratedMessagePackFormatter(typeof(External))]`, on a partial cl… | partial | C1, C2 | Generator fills partial IMessagePackFormatter<T> classes (C1, medium), but the attribute has no typeof(External) constructor (C2), so F1's example form doesn't compile; type comes from the interface. Abstract/generic/inaccessible T are rejected. Human question: is the interface-derived form acceptable as the 'e.g.' in F1? |
| **F2** Keys for the external type's members come from a **surrogate type** carrying the MessagePa… | addressed | C3, C4 | Contractless mode (public read-write, ordinal-sorted string keys) and SurrogateType mode (name+type match, surrogate not used at run time) are implemented. Medium confidence; edge cases with hidden/one-accessor overridden members; emitter templates not fully read. |
| **F3** Analyzers flag a surrogate property that has no matching property on the external type, an… | addressed | C5, C8, C11 | MsgPack022 covers surrogate member without matching target; MsgPack003 reused for missing key. Emitted from the generator pipeline, not a DiagnosticAnalyzer. Tests cover 022 but no test for the missing-[Key] surrogate path. |
| **F4** Copying MessagePack attribute definitions into Project A is explicitly rejected (reflectio… | not-checkable | — | Rejection of copying attributes into Project A is a design constraint; no claim verifies it. The surrogate approach (C4) is consistent with it, but no claim covers it directly. |
| **F5** The generated formatter is registered in the project's generated resolver like any other f… | addressed | C6, C10 | Generated formatters registered in GeneratedMessagePackResolver as ObjectSerializationInfo, excluded from hand-written discovery; a test asserts resolver registration. Medium confidence; no snapshot or tests run. |
| **N1** Only public members are serialized (confirmed with the requester). | addressed | C3, C10 | Only public read-write members are serialized in contractless mode (C3, medium); test asserts string keys across an assembly boundary. |
| **N2** Existing generation output for owned types is unchanged (snapshot tests pass). | addressed | C7, C14 | Templates emit identical 'internal sealed class' text when the new flag is false (C7, high); C14 is medium. Snapshot tests were not run, so there's no execution evidence. |
| **N3** Documentation for the new attribute and new analyzer IDs. | partial | C8, C9 | New analyzer IDs MsgPack019-022 have index entries and doc pages (C8). README covers constructor and limitation behaviour (C9). No claim verifies documentation of the attribute itself beyond the README and doc comment. |

## Claims and verdicts

### ✅ C1 · behaviour · supported (medium, info)

**Claim:** A partial class marked [GeneratedMessagePackFormatter] that implements IMessagePackFormatter<T> for a class or struct T gets a generated Serialize/Deserialize body from the generator, via ForAttributeWithMetadataName and GeneratedFormatterCollector.Collect. _(→ F1)_

**Basis:** Direct code reading of the generator pipeline, the collector and the emit path. Nothing was executed, and I found no test that asserts the generated Serialize/Deserialize text.

**Reasoning:** I followed the path from attribute discovery through Collect, the model split and emit to the templates. Every step exists and is wired together. The collector returns a model only for a partial class implementing a single IMessagePackFormatter<T> with a class or struct T, and the templates turn it into the partial class body. I did not read the full Deserialize template or confirm that the output compiles. Collect returns null for abstract, generic and inaccessible T, so "class or struct T" holds only for the supported subset. A class T also needs an accessible parameterless constructor.

**Evidence:**
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:28-35` — ForAttributeWithMetadataName on MessagePack.GeneratedMessagePackFormatterAttribute for class declarations. It builds a GeneratedFormatterRequest(formatter symbol, SurrogateType).
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:65-71` — Each request calls GeneratedFormatterCollector.Collect, and the resulting FullModel is added to modelPerType.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:34-125` — Collect requires a partial class and exactly one IMessagePackFormatter<T> interface. T must be a non-generic, non-abstract class or struct. It builds an ObjectSerializationInfo with IsUserDeclaredFormatter=true and the Formatter set to the user's class, and returns it in FullModel.ObjectInfos.
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:108` — ObjectInfos are split into per-type models, which are then emitted.
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.Emit.cs:43-47` — Each ObjectSerializationInfo is run through the int-key or string-key formatter template.
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt:14-23` — When IsUserDeclaredFormatter is set, the template emits `partial class <Formatter> : IMessagePackFormatter<T>` with a generated Serialize method, so it merges with the user's partial class. The string-key template does the same.
- code `src/MessagePack.Annotations/Attributes.cs:165-176` — The attribute class GeneratedMessagePackFormatterAttribute exists with SurrogateType, and the constants in Constants.cs match it.

### ✅ C2 · behaviour · supported (high, minor)

**Claim:** The attribute has no constructor taking typeof(External); the external type comes only from the IMessagePackFormatter<T> interface, so the usage form in F1, [GeneratedMessagePackFormatter(typeof(External))], does not compile. _(→ F1)_

**Basis:** Direct code reading of the whole attribute class, plus a repo-wide grep for other definitions or constructors.

**Reasoning:** The class has no explicit constructors, so only the implicit parameterless one exists. A positional typeof argument therefore cannot bind to a constructor, and typeof(External) cannot be a named argument either. The external type can only come from the IMessagePackFormatter<T> implemented by the annotated class, as the doc comment says. The form F1 suggests ("e.g.") does not compile. The change's own usage deliberately differs from F1. I did not compile it, so this rests on C# rules and code reading, not execution.

**Evidence:**
- code `src/MessagePack.Annotations/Attributes.cs:166-178` — GeneratedMessagePackFormatterAttribute declares no constructor, only the SurrogateType property. C# gives it an implicit parameterless constructor, so [GeneratedMessagePackFormatter(typeof(External))] has no matching constructor and gives CS1729. The external type is not a parameter.
- code `src/MessagePack.Annotations/Attributes.cs:160-163` — The XML doc example uses [GeneratedMessagePackFormatter] with no arguments, and the type comes from IMessagePackFormatter<ProjectA.MyObject>.
- deterministic  — A repo-wide grep for 'class GeneratedMessagePackFormatterAttribute' finds only this definition. A grep for 'GeneratedMessagePackFormatterAttribute(' and 'GeneratedMessagePackFormatter(typeof' finds nothing.

### ✅ C3 · behaviour · supported (medium, minor)

**Claim:** With no surrogate, every public read-write instance property and field (including inherited ones) is serialized under its name as a string key, sorted ordinally. Read-only members are skipped. _(→ F2, N1)_

**Basis:** Direct code reading of the whole contractless path in GeneratedFormatterCollector. No tests or execution were used. I did not check the emitter downstream.

**Reasoning:** The core claim matches the code: public read-write members, own and inherited, are keyed by name and sorted ordinally. Read-only members are skipped. There are two edge-case deviations. First, GetInstanceMembers keeps only the first member of each name, from the most derived type. A non-public derived member that hides a public base member of the same name therefore removes the base one. Second, a derived override that declares only one accessor of a base read-write property is seen as read-only and skipped. Neither contradicts the claim in the normal case. I did not check whether the emitter re-sorts or reorders members after this point.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:84-88` — When surrogate is null, members come from CreateContractlessMembers and isIntKey is false.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:131-140` — Members come from GetInstanceMembers filtered by IsPublicReadWrite, sorted with OrderBy(Name, StringComparer.Ordinal). Each member gets StringKey = Name, so it is serialized under its name.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:251-276` — GetInstanceMembers walks BaseType up to, but not including, object, so inherited members are included. It skips static members, implicitly declared members and indexers.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:279-285` — IsPublicReadWrite requires a property to be public with a public getter and a public setter. It requires a field to be public, not readonly and not const. Read-only members are therefore skipped.

### ✅ C4 · behaviour · supported (medium, info)

**Claim:** With SurrogateType set, keys and membership come from the surrogate's [Key]/[IgnoreMember] annotations, matched to the target's public read-write members by name and identical type. The surrogate is never instantiated at run time. _(→ F2)_

**Basis:** Direct code reading of CreateSurrogateMembers and a grep for every use of the surrogate in src. No tests run or read.

**Reasoning:** Keys and membership come from the surrogate's [Key] and [IgnoreMember] attributes, and the match is by name plus identical type to a public read-write target member. I grepped src for 'surrogate' and found it used only in the collector, the generator's input plumbing, the analyzer descriptor and the attribute docs. Nothing in the model or emitter references it, so the generated formatter has no run-time use of the surrogate. I did not read the emitter templates (.tt) in full. One nuance: GetInstanceMembers(surrogate) also returns non-public and inherited surrogate members. A private surrogate field with no [Key] and no [IgnoreMember] would therefore fail with MemberNeedsKey, rather than being silently excluded. This does not contradict the claim.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:161-213` — Iterates surrogate members only. [IgnoreMember] skips a member. The [Key] value (int or string) becomes the key. A member with no key reports MemberNeedsKey. The target is the same-named member of the formatted type, and it must be public read-write with an identical type (SymbolEqualityComparer), else SurrogateMemberNotFound. Target members the surrogate does not list are never added.
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:34-72` — The surrogate INamedTypeSymbol is read from the attribute's NamedArguments and passed only to GeneratedFormatterCollector.Collect, which is compile-time only.
- code `src/MessagePack.Annotations/Attributes.cs:153-176` — Documents the surrogate as never instantiated at run time.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:105-120` — The ObjectSerializationInfo is built from the target type and the members only. It carries no reference to the surrogate, so the emitted code has none.

### ✅ C5 · behaviour · supported (high, info)

**Claim:** Diagnostics are reported for a surrogate member with no matching target member (MsgPack022, also on a type mismatch) and for a surrogate member with no [Key] (reuses MsgPack003 MemberNeedsKey). They are emitted from the generator pipeline via RegisterSourceOutput, not from a DiagnosticAnalyzer, even though descriptors live in the analyzer class. _(→ F3)_

**Basis:** Direct reading of the whole path: the generator pipeline, the collector method and the descriptor declarations. No execution or tests were run.

**Reasoning:** Both diagnostics are created only in GeneratedFormatterCollector. Its Action<Diagnostic> callback is wired in the generator's SelectMany, and RegisterSourceOutput reports the results. A grep for SurrogateMemberNotFound and MemberNeedsKey found no use in the DiagnosticAnalyzer beyond the descriptor declarations and the SupportedDiagnostics list. MemberNeedsKey is the pre-existing MsgPack003 descriptor, so it is reused. The type-mismatch case is covered by the same condition as the missing-target case.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:169-179` — A surrogate member without an int or string [Key] reports MsgPack00xMessagePackAnalyzer.MemberNeedsKey (MsgPack003, reused).
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:189-198` — A missing target, a non-public-read-write target, or a member type mismatch each report SurrogateMemberNotFound (MsgPack022).
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:116-133` — The generatedFormatterDiagnostics SelectMany calls GeneratedFormatterCollector.Collect with diagnostics.Add. RegisterSourceOutput then calls context.ReportDiagnostic on each result.
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:345-385` — The SurrogateMemberNotFound descriptor is declared in the analyzer class and listed in SupportedDiagnostics. The grep found no analyzer code that reports it.

### ✅ C6 · behaviour · supported (medium, info)

**Claim:** Generated formatters are registered in GeneratedMessagePackResolver as ObjectSerializationInfo, and are excluded from the hand-written custom-formatter discovery so they are not registered twice. _(→ F5)_

**Basis:** Direct code reading of the full path: collector → model → resolver emit, plus the discovery filter. No execution and no test run.

**Reasoning:** Both halves of the claim are implemented. First, generated formatters become ObjectSerializationInfo and reach the resolver through ObjectInfos. Second, the attribute check in the discovery predicate excludes them from hand-written discovery. The attribute name comparison uses the same namespace and name constants as ForAttributeWithMetadataName, so the two sides match. Caveats: I did not run tests or check a snapshot of the generated resolver. A formatter that fails validation returns null, so it is neither registered nor generated, which is consistent with the claim. I found no other path that registers it twice.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:104-125` — Builds an ObjectSerializationInfo with Formatter set to the user's partial class and IsUserDeclaredFormatter=true. It is returned in FullModel.ObjectInfos.
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:28-75` — Models from GeneratedFormatterCollector.Collect are added to modelPerType, which feeds the resolver model.
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.Emit.cs:71-79` — GenerateResolver puts model.ObjectInfos into registerInfos, which feeds ResolverTemplate. This registers the generated formatter in the generated resolver. Line 43-49 emits the partial formatter body from the same ObjectInfos.
- code `src/MessagePack.SourceGenerator/GeneratorUtilities.cs:35-43` — The custom-formatter discovery transform returns null for any class carrying MessagePack.GeneratedMessagePackFormatterAttribute, so it never enters CustomFormatterInfos. Hand-written discovery does not register it a second time.

### ✅ C7 · non-change · supported (high, info)

**Claim:** Both formatter templates (.tt and generated .cs) now emit 'partial class' instead of 'internal sealed class' when Info.IsUserDeclaredFormatter is true, and the output for all other types is byte-identical to before. _(→ N2)_

**Basis:** Direct code reading of the diff hunks and the property definition. No execution or snapshot test run.

**Reasoning:** Both .tt and .cs templates emit \"partial class\" when the flag is true and \"internal sealed class\" otherwise. For owned types the flag keeps its default of false. The concatenated output is then \"\\t\" + \"internal sealed class\" + \" \" + name, which is byte-identical to the old literal. I found no other edits to these templates in the hunks. EnumTemplate and UnionTemplate still emit `internal sealed class` unchanged. The claim names only the two formatter templates, so that does not contradict it. The flag also takes part in equality (ObjectSerializationInfo.cs:168), which does not change output. I did not run the snapshot tests.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.cs:33-36` — Writes "\t", then the ternary "partial class" / "internal sealed class", then " ", then the name. When the flag is false this is the same text as the old "\tinternal sealed class ".
- code `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.cs:37-40` — Same split-and-ternary change. The false case gives the same bytes as before.
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt:14` — The .tt source carries the same ternary, so it matches the generated .cs.
- code `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.tt:18` — The .tt source carries the same ternary, so it matches the generated .cs.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/ObjectSerializationInfo.cs:17` — The property is `bool IsUserDeclaredFormatter { get; init; }`, so it defaults to false.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:118` — This is the only place that sets the flag to true. It is set only for the new user-declared formatter path.

### ✅ C8 · docs · supported (high, info)

**Claim:** Four new error diagnostics MsgPack019-022 (not partial; does not implement exactly one IMessagePackFormatter<T>; data type unsupported; surrogate member mismatch) are added, with a release-tracking entry, an index entry and a doc page each. _(→ N3, F3)_

**Basis:** Direct code reading of the descriptors and GeneratedFormatterCollector, compared with the release-tracking file, the index and the four doc pages. No execution.

**Reasoning:** Each of the four IDs has a descriptor, a call site, a release-tracking row, an index row and a doc page. The doc text matches the implemented conditions: partial check, exactly-one-interface check, generic/abstract/inaccessible data type check, and the surrogate name/type/read-write match. I found nothing contradicting the claim. The tests that would show these diagnostics firing were not examined, because the claim is about docs and release tracking.

**Evidence:**
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:318-352` — Four descriptors MsgPack019-022. Category is Usage, severity is Error, and the titles match the release-tracking entries and the doc headings.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:47-74` — 019 is reported when the class is not partial. 020 is reported when the count of IMessagePackFormatter<T> interfaces is not exactly one. 021 is reported for generic, abstract, non-class/struct or inaccessible data types.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:189-198` — 022 is reported when a surrogate member has no same-name target, the target is not public read-write, or the types differ. This matches MsgPack022.md.
- code `src/MessagePack.SourceGenerator/AnalyzerReleases.Unshipped.md:26-29` — Four release-tracking rows (Usage | Error) for MsgPack019-022.
- docs `doc/analyzers/index.md:26-29` — Four index rows linking to the new pages.
- docs `doc/analyzers/MsgPack022.md:1-31` — The four pages doc/analyzers/MsgPack019.md to MsgPack022.md exist. Each describes behaviour that the collector implements.

### ✅ C9 · docs · supported (medium, info)

**Claim:** The README promises that deserialization uses an accessible parameterless constructor, that types with only parameterized constructors are unsupported, and that nested member types resolve through the other resolvers. The code reports NoDeserializingConstructor (MsgPack007 descriptor) for a class with no parameterless constructor. _(→ N3)_

**Basis:** Direct code reading of the collector's constructor check and the descriptor ID. No execution and no test run. The nested-type resolution promise was not traced into the emitter.

**Reasoning:** The README's constructor and limitation statements are backed by the collector's isClass and parameterless-constructor check. That check emits the MsgPack007 descriptor, which I confirmed by reading the ID constant. The nested-type claim is consistent with the model (no nested formatter, no custom formatter on members), but I did not trace the emitter's use of the resolvers.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:76-81` — A class without an accessible parameterless constructor reports NoDeserializingConstructor and returns null. Structs skip the check.
- code `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs:151-159` — The NoDeserializingConstructor descriptor uses DeserializingConstructorId, which line 20 defines as "MsgPack007".
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:99-109` — constructorParameters is Array.Empty and nestedFormatterRequired is false, so constructor parameters are never matched and no nested formatters are generated.
- docs `README.md` — The Limitations list in the added section states the three promises: parameterless constructor, parameterized-only types unsupported, and nested types resolved through other resolvers.

### ✅ C10 · tests · supported (medium, info)

**Claim:** The new tests prove contractless and surrogate formatting works end to end across an assembly that does not reference MessagePack: round-trip, string keys, an array of 8 slots for surrogate keys 3 and 7, and registration in the generated resolver. _(→ F1, F2, F5, N1)_

**Basis:** Direct code reading of the tests, the fixture types and the csproj. Nothing was executed, so I did not see the tests pass.

**Reasoning:** The claim lists four things. Round-trip, string keys, an 8-slot array and resolver registration are each asserted by a specific test. The external assembly has no MessagePack reference, and the execution test project references it, so the path crosses an assembly boundary. The tests would fail if the generator did not produce these formatters, because the partial classes would be empty and would not implement the interface. A caveat is that the resolver test uses GetFormatter directly and the other tests go through CompositeResolver. Both depend on registration in the generated resolver, so this is fine. One small gap: the 8-slot test checks the array header and the round-trip, but it does not check which slots (3 and 7) are filled.

**Evidence:**
- code `tests/MessagePack.SourceGenerator.ExternalTypes/MessagePack.SourceGenerator.ExternalTypes.csproj:1-17` — The csproj has no MessagePack PackageReference or ProjectReference. The repo's Directory.Build.props adds none either.
- code `tests/MessagePack.SourceGenerator.ExternalTypes/ExternalWidget.cs:7-15` — ExternalWidget and ExternalPerson are plain POCOs with no attributes.
- code `tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypes.cs:9-37` — Two formatters are contractless. ExternalWidgetFormatter uses a surrogate with Key(3), Key(7) and an IgnoreMember property.
- test `tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypesTests.cs:12-62` — ContractlessClassRoundTrips and ContractlessStructRoundTrips cover round-trip. ContractlessClassUsesStringKeysForPublicReadWriteMembers checks the 0x82 map header and the Id and Label keys. SurrogateControlsKeysAndMembership checks that the array header is 8 and that Internal is not serialized.
- test `tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypesTests.cs:86-92` — GeneratedFormattersAreRegisteredInGeneratedResolver asserts that GeneratedMessagePackResolver.Instance.GetFormatter returns the generated formatter types.

### ✅ C11 · tests · supported (medium, info)

**Claim:** The diagnostic tests cover MsgPack019, 020, 021, 022 (missing member and type mismatch) and MsgPack005 (mixed keys). No test covers a missing [Key] on a surrogate member, the NoDeserializingConstructor path, or a struct or inherited member in surrogate mode. _(→ F3)_

**Basis:** Direct reading of the whole test file and the execution-test file; no tests were run.

**Reasoning:** The listed diagnostics are all exercised by the tests in the diff. I found no test for a missing [Key] on a surrogate member, NoDeserializingConstructor, or inherited members in surrogate mode. The one gap in my check is that I did not read ExternalPoint's definition. The claim's "no test covers a struct" could be wrong if ExternalPoint is a struct, but that case would be contractless mode, not surrogate mode, so the claim as worded still holds.

**Evidence:**
- test `tests/MessagePack.SourceGenerator.Tests/GeneratedMessagePackFormatterTests.cs:30-210` — Six tests: MsgPack019 (non-partial formatter), 020 (formatter without IMessagePackFormatter<T>), 021 (abstract type), 022 twice (missing member, type mismatch), and 005 (mixed int/string keys). No test has a surrogate member without [Key], a NoDeserializingConstructor case, or a struct or inherited member.
- test `tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypes.cs:9-37` — The execution tests use a class surrogate with [Key]/[IgnoreMember] and ExternalPoint, which may be a struct. They do not test a missing [Key] on a surrogate member, NoDeserializingConstructor, or an inherited member. ExternalPoint is not confirmed to be a struct, so a struct case there is possible.

### ✅ C12 · scope · supported (high, info)

**Claim:** Scope: the change adds behaviour no requirement item asks for. These are the type-equality requirement on surrogate members, rejection of generic/abstract types, a cast for explicit IMessagePackSerializationCallbackReceiver implementations, and reuse of MsgPack005/007/003/004-style diagnostics (KeysMustBeUnique, DoNotMixStringAndIntKeys).

**Basis:** Direct code reading of the whole new file against the requirement text (F1–F5, N1–N3).

**Reasoning:** All four behaviours are in the file. None maps to F1–F5 or N1–N3. F3 covers only a missing matching property and a missing key. The added behaviours are type-equality matching, generic/abstract rejection, the explicit-callback cast, and the reused uniqueness and key-mix diagnostics. I did not check whether the MemberNeedsKey and SurrogateMemberNotFound diagnostics satisfy F3. The claim lists "MsgPack005/007/003/004-style" IDs, and I did not map those numbers to the diagnostic descriptors. The scope claim holds regardless. Whether the extras are acceptable is for the human to decide.

**Evidence:**
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:190` — A surrogate member is rejected unless the target member's type equals the surrogate member's type. F3 only asks for flagging a surrogate property with no matching property.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:64` — Generic and abstract formatted types are rejected (IsGenericType: false, IsAbstract: false). No requirement item mentions this.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:84-85` — needsCast is computed for explicit IMessagePackSerializationCallbackReceiver implementations and passed as needsCastOnBefore/After. No requirement item mentions callbacks.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:185-202` — The existing DoNotMixStringAndIntKeys and KeysMustBeUnique diagnostics are reused for surrogate keys. F3 names only a missing key and a missing matching property.

### ✅ C13 · scope · supported (high, minor)

**Claim:** Scope: the MapModeExecutionTests project now excludes GeneratedFormatterForExternalTypes*.cs from its compile glob, so the new feature is not exercised in force-map mode.

**Basis:** Direct code reading of the csproj and the glob of matching files; no execution.

**Reasoning:** The HEAD csproj contains the added exclude, which matches the claim. The glob matches two files, so the exclusion removes both the feature's formatter and its tests from the force-map-mode build. The second half of the claim, that the feature is therefore not exercised in force-map mode, follows from that. I did not check whether other files in the project use the feature. The requirement does not mention this change. It narrows test coverage, and the reviewer should decide whether that is acceptable.

**Evidence:**
- code `tests/MessagePack.SourceGenerator.MapModeExecutionTests/MessagePack.SourceGenerator.MapModeExecutionTests.csproj:13-14` — The Compile Exclude now also lists ..\ExecutionTests\**\GeneratedFormatterForExternalTypes*.cs, and a comment says the ExternalTypes assembly is not referenced.
- code `tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypes.cs` — The glob matches this file and GeneratedFormatterForExternalTypesTests.cs in ExecutionTests. Both are now left out of the map-mode project.

### ✅ C14 · non-change · supported (medium, info)

**Claim:** Existing owned-type generation, [MessagePackObject] handling and the existing snapshot tests are unaffected by the new pipeline inputs, the extra .Combine nesting and the new IsUserDeclaredFormatter equality member. _(→ N2)_

**Basis:** Direct reading of the full Initialize method, the equality member, the templates and the formatter filter. No tests were run. I could not diff other shared files (e.g. TypeCollector) against BASE.

**Reasoning:** Without the new attribute, the generator produces the same models and the same template text as BASE. The extra Combine only changes how the tuple is indexed, and I checked each index. The new flag defaults to false and adds a false == false term to equality. Both templates emit the same 'internal sealed class' text when the flag is false. The formatter filter excludes only types carrying the new attribute. I searched HEAD for the new symbols and found them only in the files listed. I did not run the snapshot tests, and I could not confirm that TypeCollector and the other shared code are untouched, so confidence is medium.

**Evidence:**
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:36-76` — The existing MessagePackObject and union inputs still go through TypeCollector.Collect. Only the tuple access paths were re-indexed for the extra Combine (Left.Left.Left.Left and Left.Left.Left.Right). The new requests are handled in a separate loop that does nothing when there are none.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/ObjectSerializationInfo.cs:17` — IsUserDeclaredFormatter is a non-required init property. It defaults to false for every existing ObjectSerializationInfo.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/ObjectSerializationInfo.cs:168` — The new equality term compares false == false for existing types, so it does not change their equality.
- code `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs:118` — This is the only place that sets IsUserDeclaredFormatter = true.
- code `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt:14` — When the flag is false the template emits 'internal sealed class', which matches BASE (base FormatterTemplate.tt:14). StringKeyFormatterTemplate.tt:18 is the same.
- code `src/MessagePack.SourceGenerator/GeneratorUtilities.cs:35-43` — This filter excludes only classes carrying the new attribute from the hand-written formatter list. Other formatters are unaffected.
- code `src/MessagePack.SourceGenerator/MessagePackGenerator.cs:115-131` — The diagnostics pipeline is separate and reports nothing when no [GeneratedMessagePackFormatter] class exists.

## Routed to a named human

Nothing. Every claim is supported by cited evidence.

## Changed files

| File | Class | +/- |
|---|---|---|
| `README.md` | docs | +52 −0 |
| `doc/analyzers/MsgPack019.md` | docs | +26 −0 |
| `doc/analyzers/MsgPack020.md` | docs | +23 −0 |
| `doc/analyzers/MsgPack021.md` | docs | +23 −0 |
| `doc/analyzers/MsgPack022.md` | docs | +31 −0 |
| `doc/analyzers/index.md` | docs | +4 −0 |
| `src/MessagePack.Annotations/Attributes.cs` | source | +36 −0 |
| `src/MessagePack.SourceGenerator/AnalyzerReleases.Unshipped.md` | docs | +4 −0 |
| `src/MessagePack.SourceGenerator/Analyzers/MsgPack00xMessagePackAnalyzer.cs` | source | +45 −1 |
| `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs` | source | +300 −0 |
| `src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterRequest.cs` | source | +13 −0 |
| `src/MessagePack.SourceGenerator/CodeAnalysis/ObjectSerializationInfo.cs` | source | +7 −0 |
| `src/MessagePack.SourceGenerator/GeneratorUtilities.cs` | source | +3 −0 |
| `src/MessagePack.SourceGenerator/MessagePackGenerator.cs` | source | +36 −3 |
| `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.cs` | source | +3 −1 |
| `src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt` | template | +1 −1 |
| `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.cs` | source | +3 −1 |
| `src/MessagePack.SourceGenerator/Transforms/StringKey/StringKeyFormatterTemplate.tt` | template | +1 −1 |
| `src/MessagePack.SourceGenerator/Utils/Constants.cs` | source | +2 −0 |
| `tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypes.cs` | test | +50 −0 |
| `tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypesTests.cs` | test | +95 −0 |
| `tests/MessagePack.SourceGenerator.ExecutionTests/MessagePack.SourceGenerator.ExecutionTests.csproj` | build | +5 −0 |
| `tests/MessagePack.SourceGenerator.ExternalTypes/ExternalPerson.cs` | test | +15 −0 |
| `tests/MessagePack.SourceGenerator.ExternalTypes/ExternalPoint.cs` | test | +12 −0 |
| `tests/MessagePack.SourceGenerator.ExternalTypes/ExternalWidget.cs` | test | +15 −0 |
| `tests/MessagePack.SourceGenerator.ExternalTypes/MessagePack.SourceGenerator.ExternalTypes.csproj` | build | +17 −0 |
| `tests/MessagePack.SourceGenerator.MapModeExecutionTests/MessagePack.SourceGenerator.MapModeExecutionTests.csproj` | build | +2 −1 |
| `tests/MessagePack.SourceGenerator.Tests/GeneratedMessagePackFormatterTests.cs` | test | +210 −0 |

---
_Sign-off: `cev decide --report <this dir> --by "Name" accept|reject` records who accepted, what they saw, and the report hash._