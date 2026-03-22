import os
import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password=os.environ.get('VPS_PASS', ''), timeout=15)

commands = [
    # Force Traefik to restart and retry ACME challenge
    'echo "=== Restarting Traefik to retry Let s Encrypt ==="',
    'docker service update --force traefik 2>&1 | tail -5',
    'sleep 15',

    # Check ACME logs after restart
    'echo "=== ACME LOGS AFTER RESTART ==="',
    'docker service logs traefik --since 30s 2>&1 | grep -i "acme\\|letsencrypt\\|certificate\\|extrator" | tail -10',

    # Test HTTPS
    'echo "=== HTTPS TEST ==="',
    'curl -sk https://api.extratordedados.com.br/api/health',

    # Check cert details
    'echo ""',
    'echo "=== CERT INFO ==="',
    'echo | openssl s_client -connect api.extratordedados.com.br:443 -servername api.extratordedados.com.br 2>/dev/null | openssl x509 -noout -subject -issuer -dates 2>/dev/null || echo "cert check failed"',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)

ssh.close()
print("\n=== DONE ===")
