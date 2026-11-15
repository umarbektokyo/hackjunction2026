"""Function-level diff of two RoutePulse TS trees, robust to code moving between files.
python fndiff.py <old dir> <new dir> [name]   (with a name: print a unified diff of that function)"""
import difflib, glob, re, sys

HEAD = re.compile(r'^(\s*)(?:export\s+)?(?:async\s+)?(?:function\s+|(?:private|public|protected|static|readonly|\s)*)'
                  r'([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(')
KEYWORDS = {'if', 'for', 'while', 'switch', 'catch', 'return', 'function', 'else', 'new', 'await', 'typeof'}


def functions(root):
    out = {}
    for path in sorted(glob.glob(f'{root}/*.ts')):
        lines = open(path).read().split('\n')
        i = 0
        while i < len(lines):
            m = HEAD.match(lines[i])
            indent = len(m.group(1)) if m else -1
            if m and m.group(2) not in KEYWORDS and indent <= 2 and not lines[i].rstrip().endswith(';'):
                # find the opening brace, then match braces
                depth, j, started = 0, i, False
                while j < len(lines):
                    code = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|//.*', '', lines[j])
                    for ch in code:
                        if ch == '{':
                            depth += 1; started = True
                        elif ch == '}':
                            depth -= 1
                    if started and depth <= 0:
                        break
                    j += 1
                body = [l.strip() for l in lines[i:j + 1] if l.strip() and not l.strip().startswith('//')]
                key = m.group(2)
                while key in out:
                    key += "'"
                out[key] = (path.split('/')[-1], body)
                i = j + 1
                continue
            i += 1
    return out


old, new = functions(sys.argv[1]), functions(sys.argv[2])
if len(sys.argv) > 3:
    n = sys.argv[3]
    print('\n'.join(difflib.unified_diff(old.get(n, ('', []))[1], new.get(n, ('', []))[1], 'old', 'new', lineterm='', n=2)))
    sys.exit()
total = 0
for name in sorted(set(old) | set(new), key=lambda n: (new.get(n, old.get(n))[0], n)):
    o, nw = old.get(name), new.get(name)
    if o and nw and o[1] == nw[1]:
        continue
    if not o:
        print(f'NEW      {nw[0]:<14} {name} ({len(nw[1])} lines)'); total += len(nw[1]); continue
    if not nw:
        print(f'REMOVED  {o[0]:<14} {name}'); continue
    d = [l for l in difflib.unified_diff(o[1], nw[1], lineterm='', n=0) if l[:1] in '+-' and not l.startswith(('+++', '---'))]
    total += len(d)
    print(f'CHANGED  {nw[0]:<14} {name} ({len(d)} +/- lines, was in {o[0]})')
print('total changed lines', total)
