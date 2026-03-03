"""Debug rate limiting with the actual app module"""
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

# Test with actual app using Flask test client
test_script = r'''
import sys, os
os.chdir('/opt/extrator-api')
sys.path.insert(0, '/opt/extrator-api')

# Set env vars
os.environ['DB_HOST'] = '127.0.0.1'
os.environ['DB_PORT'] = '5432'
os.environ['DB_NAME'] = 'extrator'
os.environ['DB_USER'] = 'extrator'
os.environ['DB_PASSWORD'] = 'Extr4t0r_S3cur3_2026!'

from app import app, limiter

print(f"Limiter enabled: {limiter.enabled}")
print(f"Limiter storage: {limiter._storage_uri}")
print(f"Limiter key_func: {limiter._key_func}")
print(f"App extensions: {list(app.extensions.keys())}")

# List all registered rate limits
print(f"\nRate limit decorators:")
for rule in app.url_map.iter_rules():
    print(f"  {rule.rule} -> {rule.endpoint}")

# Test with Flask test client
print(f"\n=== Testing POST /api/login with test client ===")
with app.test_client() as client:
    for i in range(8):
        resp = client.post('/api/login',
            json={'username': 'admin', 'password': '1982Xandeq1982#'},
            headers={'X-Forwarded-For': '1.2.3.4'}
        )
        all_headers = dict(resp.headers)
        rate_headers = {k: v for k, v in all_headers.items() if 'limit' in k.lower() or 'rate' in k.lower() or 'retry' in k.lower()}
        print(f"  Request {i+1}: status={resp.status_code}, rate_headers={rate_headers}")
        if resp.status_code == 429:
            print(f"  BLOCKED! {resp.data.decode()[:100]}")
            break
'''

with ssh.open_sftp() as sftp:
    with sftp.open('/tmp/test_actual_limiter.py', 'w') as f:
        f.write(test_script)

print("=== Debug Flask-Limiter with actual app ===\n")
out, err = run('/opt/extrator-api/venv/bin/python /tmp/test_actual_limiter.py', timeout=30)
print(out)
if err:
    print(f"\nSTDERR: {err[:500]}")

ssh.close()
