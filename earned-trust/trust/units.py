"""Split a diff into units: changed C# or Java members, Markdown sections and file headers.

Members are found by indentation (class members sit at four spaces in both samples), not by a
parser. That is enough for the samples and is stated as a limit in CONCEPT.md.
"""

import re

MEMBER_INDENT = "    "
NAME = re.compile(r"(\w+)\s*(?:<[^()]*>)?\s*\(")      # identifier before the parameter list
FIELD = re.compile(r"(\w+)\s*(?:=|;|\{|=>)")         # property or field name


def tier(path):
    if path.endswith(".md"):
        return "doc"
    return "test" if path.startswith("tests/") else "shipped"


def _is_decl(line):
    if not line.startswith(MEMBER_INDENT) or line[4:5] in (" ", "", "{", "}", "/", "[", "@"):
        return False
    return not line.strip().startswith(("#", "return", "//"))


STRINGS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//.*')


def _end(lines, i):
    """Index of the line that closes the member declared on line i (brace counting, strings stripped)."""
    depth, raw = 0, False
    for j in range(i, len(lines)):
        if lines[j].count('"""') % 2:
            raw = not raw
            continue
        if raw:
            continue
        code = STRINGS.sub("", lines[j]).rstrip()
        depth += code.count("{") - code.count("}")
        if depth == 0 and code.endswith((";", "}")):
            return j
    return len(lines) - 1


def csharp_members(lines):
    """[(name, start, end)] with 1-based inclusive lines; start includes doc comments, attributes and annotations."""
    members, in_raw, i = [], False, 0
    while i < len(lines):
        line = lines[i]
        if line.count('"""') % 2:
            in_raw = not in_raw
            i += 1
            continue
        if in_raw or not _is_decl(line):
            i += 1
            continue
        m = NAME.search(line) or FIELD.search(line)
        start = i
        while start > 0 and lines[start - 1].startswith(MEMBER_INDENT) and lines[start - 1].strip()[:1] in ("/", "[", "*", "@"):
            start -= 1
        end = _end(lines, i)
        name = m[1] if m else line.strip()
        members.append((name, start + 1, end + 1))
        i = end + 1
    return members


def markdown_sections(lines):
    sections, fence = [], False
    for i, line in enumerate(lines):
        fence ^= line.startswith("```")
        if not fence and line.startswith("#"):
            sections.append([line.lstrip("#").strip(), i + 1, len(lines)])
            if len(sections) > 1:
                sections[-2][2] = i
    return [tuple(s) for s in sections]


def spans(path, lines):
    found = markdown_sections(lines) if path.endswith(".md") else csharp_members(lines)
    first = found[0][1] if found else len(lines) + 1
    return [("file header", 1, first - 1)] + found


def split(diff, read_new):
    """diff: {path: [hunk]} from gitdiff.diff. read_new(path) -> new file lines. Returns units."""
    units = []
    for path, hunks in diff.items():
        changed = [l for h in hunks for l in h if l[0] != " " and l[3].strip()]  # blank lines belong to no unit
        for name, start, end in spans(path, read_new(path)):
            mine = [l for l in changed if start <= l[2] <= end and not (l[0] == "-" and l[2] == end + 1)]
            if not mine:
                continue
            shown = [l for h in hunks if any(c in mine for c in h) for l in h if start <= l[2] <= end]
            units.append({
                "id": f"{path.rsplit('/', 1)[-1]}:{name}",
                "file": path, "name": name, "tier": tier(path),
                "start": start, "end": end,
                "added": sum(l[0] == "+" for l in mine), "removed": sum(l[0] == "-" for l in mine),
                "lines": [{"kind": k, "old": o, "new": n if k != "-" else None, "text": t} for k, o, n, t in shown],
            })
    return units
