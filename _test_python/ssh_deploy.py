import paramiko
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

# Upload app_vps.py via SFTP
sftp = ssh.open_sftp()

local_app = r'C:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\backend\app_vps.py'
sftp.put(local_app, '/opt/extrator-api/app.py')
print("Uploaded app.py")

sftp.close()

# Create systemd service and start
commands = [
    # Create systemd service
    """cat > /etc/systemd/system/extrator-api.service << 'EOF'
[Unit]
Description=Extrator de Dados API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/extrator-api
ExecStart=/opt/extrator-api/venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --timeout 120 app:app
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF""",

    # Reload and start
    'systemctl daemon-reload',
    'systemctl enable extrator-api',
    'systemctl restart extrator-api',
    'sleep 2',
    'systemctl status extrator-api --no-pager -l 2>&1 | head -15',

    # Test locally
    'curl -s http://127.0.0.1:8000/api/health 2>&1',

    # Verify n8n still running
    'echo "=== N8N STATUS ==="',
    'docker ps --format "{{.Names}} {{.Status}}" | grep n8n',
]

for cmd in commands:
    display = cmd.split('\n')[0][:70] if '\n' in cmd else cmd[:70]
    print(f"\n>>> {display}...")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)
    if err and 'WARNING' not in err and 'DeprecationWarning' not in err:
        print(f"  stderr: {err}")

ssh.close()
print("\n=== DEPLOY COMPLETE ===")
