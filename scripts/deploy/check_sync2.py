import paramiko
import sys

def check():
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect('185.173.110.180', username='root', password='REDACTED_PASSWORD')
    i, o, e = s.exec_command('journalctl -u extrator-api | grep SYNC')
    data = o.read().decode('utf-8', errors='replace')
    with open('_test_python/out_sync.txt', 'w', encoding='utf-8') as f:
        f.write(data)

check()
