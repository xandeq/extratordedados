"""
Step 1: Setup PostgreSQL Docker container on VPS
"""
import paramiko
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = '185.173.110.180'
VPS_USER = 'root'
VPS_PASS = '1982X@ndeq1982#'

DB_PASSWORD = 'Extr4t0r_S3cur3_2026!'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

def run(cmd, timeout=30):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(f"  {out}")
    if err and ('error' in err.lower() or 'fatal' in err.lower()):
        print(f"  STDERR: {err[:300]}")
    return out

print("=" * 60)
print("STEP 1: SETUP POSTGRESQL ON VPS")
print("=" * 60)

# Check if postgres container already exists
result = run('docker ps -a --filter name=extrator-postgres --format "{{.Names}} {{.Status}}"')
if 'extrator-postgres' in result:
    print("\n>>> PostgreSQL container already exists!")
    if 'Up' in result:
        print(">>> Container is running. Skipping creation.")
    else:
        print(">>> Container exists but not running. Starting it...")
        run('docker start extrator-postgres')
else:
    # Create data directory
    run('mkdir -p /opt/extrator-data/postgres')

    # Run PostgreSQL container
    print("\n>>> Creating PostgreSQL container...")
    cmd = (
        f'docker run -d --name extrator-postgres '
        f'--restart always '
        f'-e POSTGRES_DB=extrator '
        f'-e POSTGRES_USER=extrator '
        f'-e POSTGRES_PASSWORD={DB_PASSWORD} '
        f'-p 127.0.0.1:5432:5432 '
        f'-v /opt/extrator-data/postgres:/var/lib/postgresql/data '
        f'postgres:16-alpine'
    )
    run(cmd, timeout=120)

    # Wait for PostgreSQL to be ready
    print("\n>>> Waiting for PostgreSQL to initialize...")
    time.sleep(5)

# Verify PostgreSQL is running
print("\n--- Verification ---")
run('docker ps --filter name=extrator-postgres --format "{{.Names}} {{.Status}}"')

# Test connection
print("\n>>> Testing PostgreSQL connection...")
run(f'docker exec extrator-postgres psql -U extrator -d extrator -c "SELECT version();"')

print("\n" + "=" * 60)
print("POSTGRESQL SETUP COMPLETE")
print("=" * 60)

ssh.close()
