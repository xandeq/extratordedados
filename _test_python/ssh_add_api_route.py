import paramiko
import sys
from _secrets import vps_host, vps_user, vps_pass

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(vps_host(), username=vps_user(), password=vps_pass(), timeout=15)

# First, find the host IP that Docker containers can reach
commands_check = [
    # Get Docker bridge gateway IP
    'docker network inspect bridge --format "{{range .IPAM.Config}}{{.Gateway}}{{end}}" 2>/dev/null',
    # Get host IP
    'hostname -I | awk "{print \\$1}"',
    # Check if API is running
    'curl -s http://127.0.0.1:8000/api/health',
]

for cmd in commands_check:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    if out:
        print(f">>> {out}")

# Create Traefik dynamic config for extrator-api
# Since Traefik runs in Docker Swarm, we need host.docker.internal or the host gateway
traefik_config = """cat > /etc/easypanel/traefik/config/extrator-api.yaml << 'YAMLEOF'
http:
  routers:
    http-extrator-api:
      service: extrator-api
      rule: "Host(`api.extratordedados.com.br`)"
      entryPoints:
        - http
      middlewares:
        - redirect-to-https
    https-extrator-api:
      service: extrator-api
      rule: "Host(`api.extratordedados.com.br`)"
      entryPoints:
        - https
      tls:
        certResolver: letsencrypt
        domains:
          - main: "api.extratordedados.com.br"
  services:
    extrator-api:
      loadBalancer:
        servers:
          - url: "http://172.17.0.1:8000"
        passHostHeader: true
YAMLEOF"""

print("\n>>> Creating Traefik config...")
stdin, stdout, stderr = ssh.exec_command(traefik_config, timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)
if err:
    print(f"  err: {err}")

# Verify the file was created
print("\n>>> Verifying config...")
stdin, stdout, stderr = ssh.exec_command('cat /etc/easypanel/traefik/config/extrator-api.yaml', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# Make Gunicorn listen on all interfaces (not just 127.0.0.1) so Docker can reach it
print("\n>>> Updating Gunicorn to listen on 0.0.0.0:8000...")
update_service = """sed -i 's/--bind 127.0.0.1:8000/--bind 0.0.0.0:8000/' /etc/systemd/system/extrator-api.service && systemctl daemon-reload && systemctl restart extrator-api && sleep 2 && systemctl status extrator-api --no-pager -l 2>&1 | head -10"""

stdin, stdout, stderr = ssh.exec_command(update_service, timeout=30)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)

# Test from Docker bridge IP
print("\n>>> Testing from Docker bridge gateway...")
stdin, stdout, stderr = ssh.exec_command('curl -s http://172.17.0.1:8000/api/health', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# Verify Traefik picked up the config (check logs)
print("\n>>> Traefik should auto-reload. Checking...")
stdin, stdout, stderr = ssh.exec_command('docker service logs traefik --tail 5 2>&1 | tail -5', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

ssh.close()
print("\n=== TRAEFIK CONFIG DONE ===")
