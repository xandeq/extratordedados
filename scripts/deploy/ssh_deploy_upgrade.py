"""
Step 2: Deploy upgraded app.py, install dependencies, migrate data, restart service
"""
import paramiko
import sys
import os
from _secrets import vps_host, vps_user, vps_pass, db_password

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = vps_host()
VPS_USER = vps_user()
VPS_PASS = vps_pass()

LOCAL_APP = r'C:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\backend\app.py'
LOCAL_REQS = r'C:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\backend\requirements.txt'
REMOTE_DIR = '/opt/extrator-api'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

sftp = ssh.open_sftp()

def run(cmd, timeout=60):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(f"  {out}")
    if err:
        # Only print errors, skip warnings
        for line in err.split('\n'):
            if 'error' in line.lower() or 'fatal' in line.lower() or 'failed' in line.lower():
                print(f"  ERR: {line[:200]}")
    return out

print("=" * 60)
print("STEP 2: DEPLOY UPGRADED APPLICATION")
print("=" * 60)

# 1. Backup current app.py
print("\n--- 1. Backup current app.py ---")
run(f'cp {REMOTE_DIR}/app.py {REMOTE_DIR}/app.py.sqlite_backup')

# 2. Upload new files
print("\n--- 2. Upload new app.py and requirements.txt ---")
sftp.put(LOCAL_APP, f'{REMOTE_DIR}/app.py')
print(f"  Uploaded app.py ({os.path.getsize(LOCAL_APP)} bytes)")

sftp.put(LOCAL_REQS, f'{REMOTE_DIR}/requirements.txt')
print(f"  Uploaded requirements.txt ({os.path.getsize(LOCAL_REQS)} bytes)")

# 3. Install new dependencies
print("\n--- 3. Install Python dependencies ---")
run(f'{REMOTE_DIR}/venv/bin/pip install -r {REMOTE_DIR}/requirements.txt', timeout=120)

# 4. Migrate data from SQLite to PostgreSQL
print("\n--- 4. Migrate SQLite data to PostgreSQL ---")

migration_script = '''
import sqlite3
import psycopg2
import os

SQLITE_PATH = os.path.expanduser("~") + "/extrator.db"
PG_CONFIG = {
    'host': '127.0.0.1',
    'port': 5432,
    'dbname': 'extrator',
    'user': 'extrator',
    'password': os.environ.get('DB_PASSWORD', ''),
}

# Check if SQLite DB exists
if not os.path.exists(SQLITE_PATH):
    print("No SQLite database found. Starting fresh.")
    exit(0)

print(f"Migrating from {SQLITE_PATH}...")

# Connect to both databases
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
pg_conn = psycopg2.connect(**PG_CONFIG)
pg_cur = pg_conn.cursor()

# Check if PostgreSQL already has data
pg_cur.execute("SELECT COUNT(*) FROM users")
if pg_cur.fetchone()[0] > 0:
    print("PostgreSQL already has data. Skipping migration.")
    pg_conn.close()
    sqlite_conn.close()
    exit(0)

# Migrate users
print("Migrating users...")
users = sqlite_conn.execute("SELECT username, password_hash, is_admin, created_at FROM users").fetchall()
for u in users:
    try:
        pg_cur.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (%s, %s, %s, %s::timestamp)",
            (u['username'], u['password_hash'], bool(u['is_admin']), u['created_at'])
        )
        print(f"  User: {u['username']}")
    except Exception as e:
        print(f"  Skip user {u['username']}: {e}")

# Build user ID mapping (SQLite ID -> PG ID)
pg_cur.execute("SELECT id, username FROM users")
pg_users = {row[1]: row[0] for row in pg_cur.fetchall()}
sqlite_users = {row['id']: row['username'] for row in sqlite_conn.execute("SELECT id, username FROM users").fetchall()}

# Migrate jobs
print("Migrating jobs...")
jobs = sqlite_conn.execute("SELECT id, user_id, url, status, results_count, created_at, started_at, finished_at FROM jobs").fetchall()
job_id_map = {}  # SQLite job_id -> PG job_id
for j in jobs:
    username = sqlite_users.get(j['user_id'])
    pg_user_id = pg_users.get(username)
    if not pg_user_id:
        continue
    try:
        pg_cur.execute(
            "INSERT INTO jobs (user_id, url, status, results_count, created_at, started_at, finished_at) VALUES (%s, %s, %s, %s, %s::timestamp, %s::timestamp, %s::timestamp) RETURNING id",
            (pg_user_id, j['url'], j['status'], j['results_count'], j['created_at'], j['started_at'], j['finished_at'])
        )
        new_id = pg_cur.fetchone()[0]
        job_id_map[j['id']] = new_id
        print(f"  Job {j['id']} -> {new_id}: {j['url'][:50]}")
    except Exception as e:
        print(f"  Skip job {j['id']}: {e}")

# Migrate emails
print("Migrating emails...")
emails = sqlite_conn.execute("SELECT job_id, email, source_url, extracted_at FROM emails").fetchall()
migrated = 0
for e in emails:
    pg_job_id = job_id_map.get(e['job_id'])
    if not pg_job_id:
        continue
    try:
        normalized = e['email'].strip().lower() if e['email'] else None
        if not normalized:
            continue
        pg_cur.execute(
            "INSERT INTO emails (job_id, email, source_url, extracted_at) VALUES (%s, %s, %s, %s::timestamp) ON CONFLICT (job_id, email) DO NOTHING",
            (pg_job_id, normalized, e['source_url'], e['extracted_at'])
        )
        migrated += 1
    except Exception as e2:
        pass

print(f"  Migrated {migrated} emails")

pg_conn.commit()
pg_conn.close()
sqlite_conn.close()
print("\\nMigration complete!")
'''

# Write migration script to VPS
with sftp.open(f'{REMOTE_DIR}/migrate_to_pg.py', 'w') as f:
    f.write(migration_script)
print("  Uploaded migration script")

# Initialize PostgreSQL tables first (run app init_db)
print("\n  Initializing PostgreSQL tables...")
run(f'{REMOTE_DIR}/venv/bin/python -c "import sys; sys.path.insert(0, \\"{REMOTE_DIR}\\"); from app import init_db; init_db()"')

# Run migration
print("\n  Running data migration...")
run(f'{REMOTE_DIR}/venv/bin/python {REMOTE_DIR}/migrate_to_pg.py')

# 5. Update systemd service (add DB env vars)
print("\n--- 5. Update systemd service ---")
service_content = """[Unit]
Description=Extrator de Dados API
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/extrator-api
Environment=DB_HOST=127.0.0.1
Environment=DB_PORT=5432
Environment=DB_NAME=extrator
Environment=DB_USER=extrator
Environment=DB_PASSWORD={db_password()}
ExecStart=/opt/extrator-api/venv/bin/gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 120 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

with sftp.open('/etc/systemd/system/extrator-api.service', 'w') as f:
    f.write(service_content)
print("  Updated systemd service file")

# 6. Restart service
print("\n--- 6. Restart service ---")
run('systemctl daemon-reload')
run('systemctl restart extrator-api')

import time
time.sleep(3)

# 7. Verify
print("\n--- 7. Verification ---")
run('systemctl status extrator-api --no-pager -l 2>&1 | head -12')
run('curl -s http://127.0.0.1:8000/api/health')

sftp.close()
ssh.close()

print("\n" + "=" * 60)
print("DEPLOY COMPLETE")
print("=" * 60)
