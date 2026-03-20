"""Quick fix: Update rate limit and restart service"""
import paramiko
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = '185.173.110.180'
VPS_USER = 'root'
VPS_PASS = 'REDACTED_PASSWORD'
LOCAL_APP = r'c:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\backend\app.py'

print("Quick Fix: Rate Limit 1/hour -> 10/hour\n")

try:
    # Connect
    print("1. Connecting to VPS...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    print("   OK Connected\n")

    # Upload
    print("2. Uploading fixed app.py...")
    with ssh.open_sftp() as sftp:
        sftp.put(LOCAL_APP, '/opt/extrator-api/app.py')
    print("   OK Uploaded\n")

    # Restart
    print("3. Restarting service...")
    stdin, stdout, stderr = ssh.exec_command('systemctl restart extrator-api', timeout=10)
    stdout.channel.recv_exit_status()  # Wait for command
    time.sleep(2)
    print("   OK Restarted\n")

    # Check
    print("4. Checking status...")
    stdin, stdout, stderr = ssh.exec_command('systemctl is-active extrator-api', timeout=10)
    status = stdout.read().decode().strip()

    if status == 'active':
        print(f"   OK Service is {status}\n")

        # Health check
        print("5. Health check...")
        stdin, stdout, stderr = ssh.exec_command('curl -s http://127.0.0.1:8000/api/health', timeout=10)
        health = stdout.read().decode().strip()
        print(f"   {health}\n")

        print("=" * 50)
        print("DEPLOY SUCCESSFUL!")
        print("Rate limit updated: 1/hour -> 10/hour")
        print("=" * 50)
    else:
        print(f"   ERROR Service status: {status}")
        print("\n   Checking logs...")
        stdin, stdout, stderr = ssh.exec_command('journalctl -u extrator-api -n 20 --no-pager', timeout=10)
        logs = stdout.read().decode()
        print(logs)

    ssh.close()

except Exception as e:
    print(f"ERROR: {e}")
    print("\nTry manual deploy:")
    print("ssh root@185.173.110.180")
    print("nano /opt/extrator-api/app.py")
    print("# Line 5005: change '1/hour' to '10/hour'")
    print("systemctl restart extrator-api")
