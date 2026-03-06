"""Deploy backend to VPS - credentials from AWS Secrets Manager"""
import paramiko
import sys
import os
import json
import time

sys.stdout.reconfigure(encoding='utf-8')

# ── Fetch credentials from AWS Secrets Manager ──────────────────────────────
def get_secrets():
    try:
        import boto3
        from botocore.exceptions import ClientError
        session = boto3.session.Session()
        client = session.client(service_name='secretsmanager', region_name='us-east-1')
        response = client.get_secret_value(SecretId='extratordedados/prod')
        return json.loads(response['SecretString'])
    except Exception as e:
        print(f"   [AWS SM] {e} — usando env vars como fallback")
        return {}

secrets = get_secrets()

VPS_HOST = secrets.get('VPS_HOST') or os.environ.get('VPS_HOST', '185.173.110.180')
VPS_USER = secrets.get('VPS_USER') or os.environ.get('VPS_USER', 'root')
VPS_PASS = secrets.get('VPS_PASS') or os.environ.get('VPS_PASS', '')
DB_PASS  = secrets.get('DB_PASS')  or os.environ.get('DB_PASS', '')

if not VPS_PASS:
    print("ERRO: VPS_PASS nao encontrado no AWS SM nem em env vars")
    sys.exit(1)

LOCAL_APP = os.path.join(os.path.dirname(__file__), '..', 'project', 'backend', 'app.py')
LOCAL_REQ = os.path.join(os.path.dirname(__file__), '..', 'project', 'backend', 'requirements.txt')

# ── SSH connect ──────────────────────────────────────────────────────────────
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

def run(cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

# 1. Backup
print("1. Backing up current app.py...")
run('cp /opt/extrator-api/app.py /opt/extrator-api/app.py.pre_batch_backup')
print("   Done")

# 2. Upload
print("\n2. Uploading files via SFTP...")
with ssh.open_sftp() as sftp:
    sftp.put(os.path.abspath(LOCAL_APP), '/opt/extrator-api/app.py')
    print("   app.py uploaded")
    sftp.put(os.path.abspath(LOCAL_REQ), '/opt/extrator-api/requirements.txt')
    print("   requirements.txt uploaded")

# 3. Install deps
print("\n3. Installing dependencies...")
out, err = run('/opt/extrator-api/venv/bin/pip install -r /opt/extrator-api/requirements.txt', timeout=120)
if 'Successfully installed' in out or 'already satisfied' in out:
    print("   Dependencies OK")
else:
    print(f"   pip output: {out[:500]}")
if err and 'WARNING' not in err:
    print(f"   pip errors: {err[:300]}")

# 4. Restart
print("\n4. Restarting service...")
run('systemctl restart extrator-api')
time.sleep(3)

out, err = run('systemctl is-active extrator-api')
print(f"   Service status: {out}")

if out != 'active':
    print("\n   Service not active! Checking logs...")
    out, err = run('journalctl -u extrator-api -n 30 --no-pager')
    print(f"   Logs:\n{out}")
else:
    # 5. Health check
    print("\n5. Health check...")
    out, err = run('curl -s http://127.0.0.1:8000/api/health')
    print(f"   {out}")

    # 6. Check tables
    print("\n6. Checking tables...")
    db_pass_cmd = DB_PASS if DB_PASS else 'Extr4t0r_S3cur3_2026!'
    out, err = run(f"""PGPASSWORD='{db_pass_cmd}' psql -h 127.0.0.1 -U extrator -d extrator -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;" """)
    print(f"   {out}")

print("\n" + "=" * 50)
print("Deploy complete!")
print("=" * 50)

ssh.close()
