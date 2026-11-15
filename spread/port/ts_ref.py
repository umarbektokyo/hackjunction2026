"""TypeScript v21e reference runs with an action log: python ts_ref.py bench-1 bench-2 ...  → logs/ts-<seed>.jsonl/.log"""
import os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(HERE, '..', 'spread', '.env')):
    if '=' in line and not line.lstrip().startswith('#'):
        k, v = line.strip().split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
os.environ['SPREAD_URL'] = 'https://spread.bahnexpress.com'
os.makedirs(f'{HERE}/logs', exist_ok=True)


def run(seed):
    jl = f'{HERE}/logs/ts-{seed}.jsonl'
    if os.path.exists(jl):
        os.remove(jl)
    with open(f'{HERE}/logs/ts-{seed}.log', 'w') as f:
        subprocess.run(['nix', 'shell', 'nixpkgs#bun', '-c', 'bun', 'src/starter.ts', '--level', '8', '--seed', seed],
                       cwd=f'{HERE}/v21e-log', stdout=f, stderr=subprocess.STDOUT, env={**os.environ, 'RP_LOG': jl})
    return seed, open(f'{HERE}/logs/ts-{seed}.log').read().strip().splitlines()[-2:]


with ThreadPoolExecutor(len(sys.argv) - 1) as pool:
    for seed, tail in pool.map(run, sys.argv[1:]):
        print(seed, tail, flush=True)
