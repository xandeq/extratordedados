import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

commands = [
    # Check the Traefik services for extrator
    'echo "=== TRAEFIK SERVICES ==="',
    'docker exec $(docker ps -q -f name=traefik) wget -qO- http://localhost:8080/api/http/services 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -A10 "extrator"',

    # Try curl with verbose to see what happens
    'echo "=== CURL HTTP VERBOSE ==="',
    'curl -v http://api.extratordedados.com.br/api/health 2>&1 | head -30',

    # Try curl HTTPS with insecure
    'echo "=== CURL HTTPS VERBOSE ==="',
    'curl -vk https://api.extratordedados.com.br/api/health 2>&1 | head -30',

    # Check acme.json for the cert
    'echo "=== ACME CERTS ==="',
    'python3 -c "import json; data=json.load(open(\'/etc/easypanel/traefik/acme.json\')); certs=data.get(\'letsencrypt\',{}).get(\'Certificates\',[]); [print(c[\'domain\'][\'main\']) for c in (certs or [])]" 2>/dev/null || echo "no certs or parse error"',

    # Check firewall
    'echo "=== FIREWALL ==="',
    'ufw status 2>/dev/null || iptables -L INPUT -n 2>/dev/null | head -10',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)

ssh.close()
