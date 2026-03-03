import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

commands = [
    'echo "=== N8N STATUS ==="',
    'docker ps --format "{{.Names}} {{.Status}}" | grep n8n',

    'echo "=== EXTRATOR API STATUS ==="',
    'systemctl status extrator-api --no-pager -l 2>&1 | head -8',

    'echo "=== API HEALTH ==="',
    'curl -s https://api.extratordedados.com.br/api/health',

    'echo ""',
    'echo "=== DISK USAGE ==="',
    'df -h / | tail -1',

    'echo "=== MEMORY ==="',
    'free -h | head -2',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)

ssh.close()
