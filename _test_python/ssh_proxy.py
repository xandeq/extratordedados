import paramiko
import sys
from _secrets import vps_host, vps_user, vps_pass

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(vps_host(), username=vps_user(), password=vps_pass(), timeout=15)

# Check how Traefik is configured (EasyPanel uses Docker labels)
commands = [
    # Check traefik config
    'echo "=== TRAEFIK CONFIG ==="',
    'docker service inspect traefik --format "{{json .Spec.TaskTemplate.ContainerSpec.Mounts}}" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "no mounts"',

    # Check traefik volumes
    'echo "=== TRAEFIK VOLUMES ==="',
    'find /etc/traefik /opt/traefik /data/traefik -name "*.yml" -o -name "*.toml" -o -name "*.yaml" 2>/dev/null || echo "not found"',

    # Check easypanel data
    'echo "=== EASYPANEL DATA ==="',
    'ls /etc/easypanel/ 2>/dev/null || echo "no easypanel dir"',
    'ls /data/ 2>/dev/null | head -10',

    # Check docker volumes
    'echo "=== DOCKER VOLUMES ==="',
    'docker volume ls 2>/dev/null | head -10',

    # Check if nginx is available as alternative
    'echo "=== NGINX ==="',
    'which nginx 2>/dev/null && nginx -v 2>&1 || echo "nginx not installed"',

    # Check traefik dynamic config
    'echo "=== TRAEFIK DOCKER LABELS ==="',
    'docker service inspect traefik --format "{{json .Spec.Labels}}" 2>/dev/null',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)

ssh.close()
