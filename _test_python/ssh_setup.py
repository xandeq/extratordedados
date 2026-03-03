import paramiko
import sys
import os

# Force UTF-8
sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

commands = [
    'mkdir -p /opt/extrator-api',
    'python3 -m venv /opt/extrator-api/venv',
    '/opt/extrator-api/venv/bin/pip install flask flask-cors requests beautifulsoup4 gunicorn 2>&1 | tail -10',
    '/opt/extrator-api/venv/bin/python3 -c "import flask; import requests; from bs4 import BeautifulSoup; print(\'ALL OK - Flask \' + flask.__version__)"',
]

for cmd in commands:
    print(f">>> {cmd[:60]}...")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)
    if err and 'WARNING' not in err:
        print(f"  err: {err}")
    print()

ssh.close()
print("DONE!")
