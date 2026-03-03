"""Deploy batch scraping update to VPS"""
import paramiko
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = '185.173.110.180'
VPS_USER = 'root'
VPS_PASS = '1982X@ndeq1982#'

LOCAL_APP = os.path.join(os.path.dirname(__file__), '..', 'project', 'backend', 'app.py')
LOCAL_REQ = os.path.join(os.path.dirname(__file__), '..', 'project', 'backend', 'requirements.txt')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

def run(cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

# 1. Backup current app.py
print("1. Backing up current app.py...")
run('cp /opt/extrator-api/app.py /opt/extrator-api/app.py.pre_batch_backup')
print("   Done")

# 2. Upload files
print("\n2. Uploading files via SFTP...")
with ssh.open_sftp() as sftp:
    sftp.put(os.path.abspath(LOCAL_APP), '/opt/extrator-api/app.py')
    print("   app.py uploaded")
    sftp.put(os.path.abspath(LOCAL_REQ), '/opt/extrator-api/requirements.txt')
    print("   requirements.txt uploaded")

# 3. Install dependencies
print("\n3. Installing dependencies...")
out, err = run('/opt/extrator-api/venv/bin/pip install -r /opt/extrator-api/requirements.txt', timeout=120)
if 'Successfully installed' in out or 'already satisfied' in out:
    print("   Dependencies OK")
else:
    print(f"   pip output: {out[:500]}")
if err and 'WARNING' not in err:
    print(f"   pip errors: {err[:300]}")

# 4. Restart service
print("\n4. Restarting service...")
run('systemctl restart extrator-api')
import time
time.sleep(3)

# 5. Check status
out, err = run('systemctl is-active extrator-api')
print(f"   Service status: {out}")

if out != 'active':
    print("\n   Service not active! Checking logs...")
    out, err = run('journalctl -u extrator-api -n 30 --no-pager')
    print(f"   Logs:\n{out}")
else:
    # 6. Health check
    print("\n5. Health check...")
    out, err = run('curl -s http://127.0.0.1:8000/api/health')
    print(f"   {out}")

    # 7. Check tables exist
    print("\n6. Checking new tables...")
    out, err = run("""PGPASSWORD='Extr4t0r_S3cur3_2026!' psql -h 127.0.0.1 -U extrator -d extrator -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;" """)
    print(f"   {out}")

print("\n" + "=" * 50)
print("Deploy complete!")
print("=" * 50)

ssh.close()
