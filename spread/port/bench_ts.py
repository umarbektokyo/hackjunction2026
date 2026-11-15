"""Bench RoutePulse TS (one commit dir) on bench-N seeds: python bench_ts.py <src dir> <name> <first> <n> <jobs>."""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
src, name, first, n, jobs = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, 'logs')
os.makedirs(LOGS, exist_ok=True)
for line in open(os.path.join(HERE, '..', 'spread', '.env')):
    if '=' in line and not line.lstrip().startswith('#'):
        k, v = line.strip().split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
os.environ['SPREAD_URL'] = 'https://spread.bahnexpress.com'


def money(s):
    return round(float(s.replace(',', '')) * 100)


def run(seed):
    txt = ''
    for attempt in range(6):
        log = f'{LOGS}/{name}-{seed}.log'
        with open(log, 'w') as f:
            subprocess.run(['nix', 'shell', 'nixpkgs#bun', '-c', 'bun', 'src/starter.ts', '--level', '8', '--seed', seed],
                           cwd=src, stdout=f, stderr=subprocess.STDOUT)
        txt = open(log).read()
        world = (re.findall(r'world (\w+)', txt) or [None])[0]
        m = re.search(r'^End\s+margin €\s*([-\d,.]+)\s+revenue €\s*([-\d,.]+)\s+(\d+) orders\s+([\d.]+)% on time\s+([\d.]+)% not delivered', txt, re.M)
        if m:
            ot = float(m.group(4)) / 100
            return {'seed': seed, 'world': world, 'marginCents': money(m.group(1)), 'revenueCents': money(m.group(2)),
                    'wonOrders': int(m.group(3)), 'onTimeShare': ot, 'undeliveredShare': float(m.group(5)) / 100, 'ranked': ot >= 0.9}
        print(f'retry {seed} {attempt}: {txt[-200:]!r}', flush=True)
        time.sleep(10)
    return {'seed': seed, 'error': txt[-300:]}


seeds = [f'bench-{i}' for i in range(first, first + n)]
with ThreadPoolExecutor(jobs) as pool:
    rows = list(pool.map(run, seeds))
with open(f'{LOGS}/bench.jsonl', 'a') as f:
    f.write(json.dumps({'name': name, 'bot': 'routepulse-ts', 'level': 8, 'params': {'src': src}, 'rows': rows}) + '\n')
ok = [r for r in rows if 'marginCents' in r]
print(f"DONE {name} n={len(ok)} mean €{sum(r['marginCents'] for r in ok) / 100 / max(1, len(ok)):,.0f} "
      f"worst {min((r['onTimeShare'] for r in ok), default=0):.1%} unranked {sum(not r['ranked'] for r in ok)}", flush=True)
