"""Python port (bot5.py) runs with an action log: python py_ref.py bench-1 ...  → logs/py-<seed>.jsonl/.log, then diff."""
import os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
SPREAD = os.path.join(HERE, '..', 'spread')
PY = '/home/ayo/Projects/hackjunction2026/.venv/bin/python'
for line in open(os.path.join(SPREAD, '.env')):
    if '=' in line and not line.lstrip().startswith('#'):
        k, v = line.strip().split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
os.environ['SPREAD_URL'] = 'https://spread.bahnexpress.com'
try:
    import certifi  # noqa: F401
except ImportError:
    pass
cert = subprocess.run([PY, '-c', 'import certifi;print(certifi.where())'], capture_output=True, text=True).stdout.strip()
if cert:
    os.environ['SSL_CERT_FILE'] = cert


def run(seed):
    jl = f'{HERE}/logs/py-{seed}.jsonl'
    if os.path.exists(jl):
        os.remove(jl)
    with open(f'{HERE}/logs/py-{seed}.log', 'w') as f:
        subprocess.run([PY, '-W', 'ignore', 'bot5.py', '--level', '8', '--seed', seed], cwd=SPREAD, stdout=f,
                       stderr=subprocess.STDOUT, env={**os.environ, 'RP_LOG': jl})
    tail = open(f'{HERE}/logs/py-{seed}.log').read().strip().splitlines()[-3:]
    diff = subprocess.run([sys.executable, os.path.join(SPREAD, 'rp_diff.py'), f'{HERE}/logs/ts-{seed}.jsonl', jl],
                          capture_output=True, text=True).stdout
    return seed, tail, diff


with ThreadPoolExecutor(len(sys.argv) - 1) as pool:
    for seed, tail, diff in pool.map(run, sys.argv[1:]):
        print(f'=== {seed}\n' + '\n'.join(tail) + '\n' + diff[:3000], flush=True)
