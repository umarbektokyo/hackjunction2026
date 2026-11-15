"""Live rehearsal of bot5.py --world on a practice world paced like the final (pace.py --final-clock).
    python port/rehearse.py pace <seed>        start the pacer (prints the world id)
    python port/rehearse.py desk <world id>    start the desk on that world (restart = run again)"""
import os, subprocess, sys
SPREAD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = '/home/ayo/Projects/hackjunction2026/.venv/bin/python'
for line in open(os.path.join(SPREAD, '.env')):
    if '=' in line and not line.lstrip().startswith('#'):
        k, v = line.strip().split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
os.environ['SPREAD_URL'] = 'https://spread.bahnexpress.com'
cert = subprocess.run([PY, '-c', 'import certifi;print(certifi.where())'], capture_output=True, text=True).stdout.strip()
if cert:
    os.environ['SSL_CERT_FILE'] = cert
os.makedirs(os.path.join(SPREAD, 'logs'), exist_ok=True)
mode, arg = sys.argv[1], sys.argv[2]
cmd = [PY, '-W', 'ignore', 'pace.py', '--seed', arg, '--final-clock', '--wait', '20'] if mode == 'pace' else \
      [PY, '-W', 'ignore', 'bot5.py', '--world', arg]
os.execvpe(PY, cmd, {**os.environ, 'PYTHONUNBUFFERED': '1'}) if False else None
os.chdir(SPREAD)
os.execve(PY, cmd, {**os.environ, 'PYTHONUNBUFFERED': '1'})
