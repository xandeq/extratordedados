import paramiko
import sys
import os

host = '185.173.110.180'
user = 'root'
password = 'REDACTED_PASSWORD'
local_app_py = 'project/backend/app.py'
remote_app_py = '/opt/extrator-api/app.py'

print(f"Deploying {local_app_py} to {host}...")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)

    print("Uploading file via SFTP...")
    sftp = ssh.open_sftp()
    sftp.put(local_app_py, remote_app_py)
    sftp.close()
    print("Upload complete!")

    print("Restarting extrator-api service...")
    stdin, stdout, stderr = ssh.exec_command('systemctl restart extrator-api')
    print(stdout.read().decode('utf-8'))
    print(stderr.read().decode('utf-8'))

    print("Checking status...")
    stdin, stdout, stderr = ssh.exec_command('systemctl status extrator-api | head -n 5')
    print(stdout.read().decode('utf-8'))

    ssh.close()
    print("Deploy successful!")

except Exception as e:
    print(f"Deploy failed: {e}")
    sys.exit(1)
