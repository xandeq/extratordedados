"""Quick deploy: upload app.py and restart service"""
import paramiko
import sys
import os
import time

sys.stdout.reconfigure(encoding='utf-8')

LOCAL_APP = r'C:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\backend\app.py'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

sftp = ssh.open_sftp()
sftp.put(LOCAL_APP, '/opt/extrator-api/app.py')
print(f"Uploaded app.py ({os.path.getsize(LOCAL_APP)} bytes)")
sftp.close()

stdin, stdout, stderr = ssh.exec_command('systemctl restart extrator-api', timeout=15)
stdout.read()
time.sleep(3)

stdin, stdout, stderr = ssh.exec_command('curl -s http://127.0.0.1:8000/api/health', timeout=10)
print(f"Health: {stdout.read().decode('utf-8')}")

ssh.close()
print("Deploy done.")
