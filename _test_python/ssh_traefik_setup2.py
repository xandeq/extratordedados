import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

commands = [
    # Check main.yaml - the core Traefik config
    'echo "=== MAIN CONFIG ==="',
    'cat /etc/easypanel/traefik/config/main.yaml',

    # Check how Traefik Docker service is configured
    'echo "=== TRAEFIK SERVICE FULL ==="',
    'docker service inspect traefik --format "{{json .Spec.TaskTemplate.ContainerSpec}}" 2>/dev/null | python3 -m json.tool 2>/dev/null || docker service inspect traefik 2>/dev/null | head -80',

    # Check traefik ports
    'echo "=== TRAEFIK PORTS ==="',
    'docker service inspect traefik --format "{{json .Endpoint.Ports}}" 2>/dev/null',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)

ssh.close()
