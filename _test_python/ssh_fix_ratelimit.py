"""Debug and fix Flask-Limiter on VPS"""
import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

# Test Flask-Limiter in isolation
print("=== Testing Flask-Limiter in isolation ===\n")

test_script = r'''
import sys
sys.path.insert(0, '/opt/extrator-api')

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200/hour"],
    storage_uri="memory://",
)

@app.route('/test')
@limiter.limit("3/minute")
def test():
    return "OK"

# Test with Flask test client
with app.test_client() as client:
    for i in range(5):
        resp = client.get('/test')
        rl_headers = {k: v for k, v in resp.headers if 'limit' in k.lower() or 'rate' in k.lower() or 'retry' in k.lower()}
        print(f"Request {i+1}: status={resp.status_code}, headers={rl_headers}")
        if resp.status_code == 429:
            print(f"  RATE LIMITED! Body: {resp.data.decode()[:100]}")
            break
'''

with ssh.open_sftp() as sftp:
    with sftp.open('/tmp/test_limiter.py', 'w') as f:
        f.write(test_script)

out, err = run('/opt/extrator-api/venv/bin/python /tmp/test_limiter.py')
print(out)
if err:
    print(f"ERR: {err[:500]}")

ssh.close()
