import os
"""Debug rate limiting directly on VPS (bypass Traefik)"""
import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password=os.environ.get('VPS_PASS', ''), timeout=15)

def run(cmd, timeout=15):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

# Test rate limiting directly (no Traefik)
print("=== Rate Limit Test (direct to Gunicorn, bypass Traefik) ===\n")

# Send 8 login requests directly to port 8000
cmd = '''
for i in $(seq 1 8); do
  RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8000/api/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"REDACTED_PASSWORD"}')
  echo "Request $i: HTTP $RESP"
done
'''
out, err = run(cmd, timeout=30)
print(out)
if err:
    print(f"STDERR: {err[:300]}")

# Check Flask-Limiter import and status
print("\n=== Check Flask-Limiter ===")
check_cmd = '''
/opt/extrator-api/venv/bin/python -c "
from flask_limiter import Limiter
print(f'Flask-Limiter version: {Limiter.__module__}')
import flask_limiter
print(f'Package: {flask_limiter.__version__}')
"
'''
out, err = run(check_cmd)
print(out)
if err:
    print(f"ERR: {err[:200]}")

# Check if there are gunicorn workers
print("\n=== Gunicorn Workers ===")
out, err = run("ps aux | grep gunicorn | grep -v grep")
print(out)

# Test with verbose headers
print("\n=== Test with full response headers ===")
cmd = '''
curl -s -D - -X POST http://127.0.0.1:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"REDACTED_PASSWORD"}' 2>&1 | head -20
'''
out, err = run(cmd)
print(out)

ssh.close()
