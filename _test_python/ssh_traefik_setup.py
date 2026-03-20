import os
import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password=os.environ.get('VPS_PASS', ''), timeout=15)

commands = [
    # First, check what's in the traefik config directory
    'echo "=== TRAEFIK DIR ==="',
    'ls -la /etc/easypanel/traefik/',

    # Check existing dynamic config
    'echo "=== EXISTING DYNAMIC CONFIG ==="',
    'cat /etc/easypanel/traefik/dynamic.yml 2>/dev/null || echo "no dynamic.yml"',
    'cat /etc/easypanel/traefik/traefik.yml 2>/dev/null || echo "no traefik.yml"',

    # Check static config
    'echo "=== STATIC CONFIG ==="',
    'find /etc/easypanel/traefik -type f 2>/dev/null',

    # Check traefik entrypoints
    'echo "=== TRAEFIK SERVICE DETAILS ==="',
    'docker service inspect traefik --format "{{json .Spec.TaskTemplate.ContainerSpec.Args}}" 2>/dev/null',

    # Check if traefik has file provider enabled
    'echo "=== TRAEFIK COMMAND ==="',
    'docker service inspect traefik --format "{{json .Spec.TaskTemplate.ContainerSpec.Command}}" 2>/dev/null',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)
    if err and 'WARNING' not in err:
        print(f"  err: {err}")

ssh.close()
