import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

commands = [
    # Check if config file exists and is valid
    'echo "=== CONFIG FILE ==="',
    'ls -la /etc/easypanel/traefik/config/',

    # Check Traefik logs for errors loading config
    'echo "=== TRAEFIK LOGS (last 20) ==="',
    'docker service logs traefik --tail 20 2>&1 | grep -v "client version 1.24"',

    # Test API is still running locally
    'echo "=== API LOCAL TEST ==="',
    'curl -s http://127.0.0.1:8000/api/health',

    # Test from host IP
    'echo ""',
    'echo "=== API FROM HOST IP ==="',
    'curl -s http://185.173.110.180:8000/api/health',

    # Check if Traefik can reach the API via docker bridge
    'echo ""',
    'echo "=== API FROM DOCKER BRIDGE ==="',
    'curl -s http://172.17.0.1:8000/api/health',

    # Check Traefik routers via API
    'echo ""',
    'echo "=== TRAEFIK ROUTERS (API) ==="',
    'curl -s http://127.0.0.1:8080/api/http/routers 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -A5 "extrator"',

    # Check Traefik services via API
    'echo ""',
    'echo "=== TRAEFIK SERVICES (API) ==="',
    'curl -s http://127.0.0.1:8080/api/http/services 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -A5 "extrator"',

    # Check if port 8080 is accessible inside the swarm
    'echo ""',
    'echo "=== TRAEFIK DASHBOARD ==="',
    'docker exec $(docker ps -q -f name=traefik) wget -qO- http://localhost:8080/api/http/routers 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -A3 "extrator" || echo "exec failed, trying another way"',

    # Try reaching traefik API from within the container
    'echo ""',
    'echo "=== TRAEFIK ROUTERS FROM INSIDE ==="',
    'docker ps -q -f name=traefik',
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)

ssh.close()
