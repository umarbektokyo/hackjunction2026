"""Play the final with bot5.py: python port/final.py  (waits for the final, rejoins on restart; logs to stdout)."""
import os, subprocess
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
os.chdir(SPREAD)
os.execve(PY, [PY, '-W', 'ignore', 'bot5.py', '--final'], {**os.environ, 'PYTHONUNBUFFERED': '1'})
