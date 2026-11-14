# #2283 Generator and analyzer crash with IndexOutOfRangeException on a closed generic struct from a referenced assembly

Source: https://github.com/MessagePack-CSharp/MessagePack-CSharp/issues/2283

#### Bug description

Both `MessagePackGenerator` (CS8785) and `MsgPack00xMessagePackAnalyzer` (AD0001) throw `IndexOutOfRangeException` when a `[MessagePackObject]` type has a member whose type is a **closed generic value type defined in a referenced assembly**.

Because the generator then "will not contribute to the output", the compiling assembly silently ends up with **no generated resolver at all**. It is only a warning, so a normal build looks fine, but trimmed and NativeAOT apps fail at runtime. In our case three assemblies of a large app had been shipping without a resolver across two releases before we noticed.

#### Repro steps

Two projects. `lib`:

```csharp
using MessagePack;
namespace Lib;

[MessagePackObject]
public partial record struct Item<T>([property: Key(0)] string Key);
```

`app`, with a `ProjectReference` to `lib`:

```csharp
using MessagePack; using Lib;
namespace App;

[MessagePackObject]
public sealed partial record Cmd([property: Key(0)] string Scope)
{
    [Key(1)] public Item<int> Member { get; init; }
}
```

Then `dotnet build` on `app`. Both projects are in the attached `mp-repro.zip`.

#### Expected behavior

A clean build, with a generated resolver in `app`.
#### Actual behavior

```
CSC : warning CS8785: Generator 'MessagePackGenerator' failed to generate source. It will not
contribute to the output and compilation errors may occur as a result. Exception was of type
'IndexOutOfRangeException' with message 'Index was outside the bounds of the array.'.
CSC : warning AD0001: Analyzer 'MessagePack.SourceGenerator.Analyzers.MsgPack00xMessagePackAnalyzer'
threw an exception of type 'System.IndexOutOfRangeException' with message 'Index was outside the
bounds of the array.'.
```

`app.dll` contains no `GeneratedMessagePackResolver`.

- Version used: MessagePack 3.1.8
- Runtime: .NET 10 (SDK 10.0.204), Windows 11

#### Additional context

**What triggers it.** `Item` is declared in `lib`, `Cmd` in `app`:

| `Item` declared as | result |
|---|---|
| `record struct Item<T>` | **crash** |
| `struct Item<T>` | **crash** |
| `struct Item` | ok |
| `record struct Item` | ok |
| `class Item<T>` | ok |
| `record class Item<T>` | ok |

So it needs all three of: **generic**, **value type**, **from a referenced assembly**. Moving the identical `Item<T>` declaration into `app` itself makes the crash disappear, which is what makes this specific to metadata symbols.
**Stack trace.**

```
System.IndexOutOfRangeException: Index was outside the bounds of the array.
   at TypeCollector.GetObjectInfo(INamedTypeSymbol formattedType, ISymbol callerSymbol)
   at TypeCollector.CollectGeneric(INamedTypeSymbol type, ISymbol callerSymbol) in TypeCollector.cs:line 661
   at TypeCollector.CollectCore(ITypeSymbol typeSymbol, ISymbol callerSymbol) in TypeCollector.cs:line 371
   at TypeCollector.GetObjectInfo(INamedTypeSymbol formattedType, ISymbol callerSymbol) in TypeCollector.cs:line 1062
   at TypeCollector.CollectCore(ITypeSymbol typeSymbol, ISymbol callerSymbol) in TypeCollector.cs:line 386
   at TypeCollector.Collect() in TypeCollector.cs:line 300
   at MsgPack00xMessagePackAnalyzer.AnalyzeSymbol(SymbolAnalysisContext, ReferenceSymbols, AnalyzerOptions) in MsgPack00xMessagePackAnalyzer.cs:line 431
```

`CollectGeneric` line 661 is the closed-generic branch that calls `GetObjectInfo` directly:

```csharp
else
{
    // NOTE: ... closed generic types such as `Foo<string>` are not registered as a formatter.
    this.GetObjectInfo(type, callerSymbol);
```

so `GetObjectInfo` runs against a type that has no syntax. Several diagnostic paths inside it index `DeclaringSyntaxReferences[0]` directly (lines 735, 1009, 1101) instead of using `FirstOrDefault()` the way the neighbouring `GetIdentifierLocation` / `GetLocation` / `GetParameterListLocation` helpers already do, and that collection is empty for a metadata symbol. I did not narrow down which of the three fires.

**Getting the stack trace.** Console output truncates the exception to its message; `-p:ErrorLog=out.sarif` preserves the full description, including the stack trace and an `ISymbol:` context line naming the offending type:

```
dotnet build -p:ErrorLog=out.sarif
```

**Workaround.** Putting `[MessagePackFormatter(typeof(ItemFormatter<>))]` on the generic value type short-circuits `CollectCore` (line 356) before `GetObjectInfo` is reached, at the cost of hand-writing the formatter.

**Possibly related:** #2092 reports CS8785 from the v3 generator, but with a different inner exception and no repro.

[mp-repro.zip](https://github.com/user-attachments/files/30408133/mp-repro.zip)
