import paramiko
import sys
from _secrets import vps_host, vps_user, vps_pass

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(vps_host(), username=vps_user(), password=vps_pass(), timeout=15)

commands = [
    # Test HTTPS with -k (ignore self-signed cert)
    'echo "=== HTTPS API RESPONSE ==="',
    'curl -sk https://api.extratordedados.com.br/api/health',

    # Test HTTP with follow redirects
    'echo ""',
    'echo "=== HTTP FOLLOW REDIRECT ==="',
    'curl -sLk http://api.extratordedados.com.br/api/health',

    # Test login endpoint
    'echo ""',
    'echo "=== LOGIN TEST ==="',
    'curl -sk -X POST https://api.extratordedados.com.br/api/login -H "Content-Type: application/json" -d \'{"username":"admin","password":"REDACTED_PASSWORD"}\'',

    # Check Traefik ACME logs
    'echo ""',
    'echo "=== ACME LOGS ==="',
    'docker service logs traefik 2>&1 | grep -i "acme\|letsencrypt\|certificate\|extrator" | tail -10',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)

ssh.close()
