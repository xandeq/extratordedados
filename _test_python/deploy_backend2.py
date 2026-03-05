"""Deploy updated app.py to VPS"""
import paramiko
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = '185.173.110.180'
VPS_USER = 'root'
VPS_PASS = 'REDACTED_PASSWORD'
LOCAL_APP = r'c:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\backend\app.py'

print("Deploying normalization improvements to VPS...\n")

try:
    # Connect
    print("1. Connecting to VPS...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=30)
    print("   Connected\n")

    # Upload
    print("2. Uploading app.py...")
    with ssh.open_sftp() as sftp:
        sftp.put(LOCAL_APP, '/opt/extrator-api/app.py')
    print("   Uploaded\n")

    # Restart
    print("3. Restarting service...")
    stdin, stdout, stderr = ssh.exec_command('systemctl restart extrator-api', timeout=30)
    stdout.channel.recv_exit_status()
    time.sleep(3)
    print("   Restarted\n")

    # Status check
    print("4. Checking status...")
    stdin, stdout, stderr = ssh.exec_command('systemctl is-active extrator-api', timeout=10)
    status = stdout.read().decode().strip()
    print(f"   Service: {status}\n")

    if status == 'active':
        print("5. Health check...")
        stdin, stdout, stderr = ssh.exec_command('curl -s http://127.0.0.1:8000/api/health', timeout=10)
        health = stdout.read().decode().strip()
        print(f"   {health}\n")
        print("DEPLOY SUCCESSFUL!")
    else:
        print("ERROR: Service not active!")
        stdin, stdout, stderr = ssh.exec_command('journalctl -u extrator-api -n 30 --no-pager', timeout=15)
        print(stdout.read().decode())

    ssh.close()

except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
