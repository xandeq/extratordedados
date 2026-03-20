import os
import paramiko
import ssl
import socket
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 60)
print("DIAGNOSTICO HTTPS - extratordedados.com.br")
print("=" * 60)

# 1. Check SSL cert on HostGator (extratordedados.com.br)
print("\n--- 1. SSL Certificate: extratordedados.com.br (HostGator) ---")
try:
    context = ssl.create_default_context()
    with socket.create_connection(('extratordedados.com.br', 443), timeout=10) as sock:
        with context.wrap_socket(sock, server_hostname='extratordedados.com.br') as ssock:
            cert = ssock.getpeercert()
            print(f"  Subject: {cert.get('subject', 'N/A')}")
            print(f"  Issuer: {cert.get('issuer', 'N/A')}")
            print(f"  Not Before: {cert.get('notBefore', 'N/A')}")
            print(f"  Not After: {cert.get('notAfter', 'N/A')}")
            san = cert.get('subjectAltName', [])
            print(f"  SANs: {[s[1] for s in san]}")
            print(f"  TLS Version: {ssock.version()}")
            print(f"  Cipher: {ssock.cipher()}")
            print("  STATUS: VALID SSL")
except ssl.SSLCertVerificationError as e:
    print(f"  SSL CERT ERROR: {e}")
except Exception as e:
    print(f"  CONNECTION ERROR: {e}")

# 2. Check SSL cert on API (api.extratordedados.com.br)
print("\n--- 2. SSL Certificate: api.extratordedados.com.br (VPS/Traefik) ---")
try:
    context = ssl.create_default_context()
    with socket.create_connection(('api.extratordedados.com.br', 443), timeout=10) as sock:
        with context.wrap_socket(sock, server_hostname='api.extratordedados.com.br') as ssock:
            cert = ssock.getpeercert()
            print(f"  Subject: {cert.get('subject', 'N/A')}")
            print(f"  Issuer: {cert.get('issuer', 'N/A')}")
            print(f"  Not Before: {cert.get('notBefore', 'N/A')}")
            print(f"  Not After: {cert.get('notAfter', 'N/A')}")
            san = cert.get('subjectAltName', [])
            print(f"  SANs: {[s[1] for s in san]}")
            print(f"  TLS Version: {ssock.version()}")
            print(f"  Cipher: {ssock.cipher()}")
            print("  STATUS: VALID SSL")
except ssl.SSLCertVerificationError as e:
    print(f"  SSL CERT ERROR: {e}")
except Exception as e:
    print(f"  CONNECTION ERROR: {e}")

# 3. DNS resolution check
print("\n--- 3. DNS Resolution ---")
for host in ['extratordedados.com.br', 'api.extratordedados.com.br']:
    try:
        ips = socket.getaddrinfo(host, 443, socket.AF_INET)
        ip = ips[0][4][0]
        print(f"  {host} -> {ip}")
    except Exception as e:
        print(f"  {host} -> ERROR: {e}")

# 4. Test API call with Origin headers (simulating browser CORS preflight)
print("\n--- 4. CORS Preflight Tests ---")
import http.client

# Test OPTIONS preflight from HTTPS origin
for origin in ['https://extratordedados.com.br', 'http://extratordedados.com.br']:
    try:
        context = ssl.create_default_context()
        conn = http.client.HTTPSConnection('api.extratordedados.com.br', 443, timeout=10, context=context)
        headers = {
            'Origin': origin,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        }
        conn.request('OPTIONS', '/api/login', headers=headers)
        resp = conn.getresponse()
        print(f"\n  OPTIONS /api/login (Origin: {origin})")
        print(f"    Status: {resp.status}")
        for h in ['Access-Control-Allow-Origin', 'Access-Control-Allow-Methods',
                   'Access-Control-Allow-Headers', 'Access-Control-Allow-Credentials']:
            val = resp.getheader(h)
            if val:
                print(f"    {h}: {val}")
        conn.close()
    except Exception as e:
        print(f"\n  OPTIONS (Origin: {origin}): ERROR - {e}")

# 5. Test actual POST login from both origins
print("\n--- 5. POST Login Tests ---")
for origin in ['https://extratordedados.com.br', 'http://extratordedados.com.br']:
    try:
        context = ssl.create_default_context()
        conn = http.client.HTTPSConnection('api.extratordedados.com.br', 443, timeout=10, context=context)
        body = json.dumps({'username': 'admin', 'password': 'REDACTED_PASSWORD'})
        headers = {
            'Content-Type': 'application/json',
            'Origin': origin,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        conn.request('POST', '/api/login', body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        print(f"\n  POST /api/login (Origin: {origin})")
        print(f"    Status: {resp.status}")
        print(f"    ACAO: {resp.getheader('Access-Control-Allow-Origin')}")
        print(f"    Body: {data[:100]}")
        conn.close()
    except Exception as e:
        print(f"\n  POST (Origin: {origin}): ERROR - {e}")

# 6. Check Traefik logs on VPS
print("\n--- 6. Traefik & API Status on VPS ---")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('185.173.110.180', username='root', password=os.environ.get('VPS_PASS', ''), timeout=15)

    commands = [
        ('Traefik status', 'docker service ls --filter name=traefik --format "{{.Name}} {{.Replicas}}"'),
        ('API service status', 'systemctl is-active extrator-api'),
        ('API port listening', 'ss -tlnp | grep 8000'),
        ('Recent Traefik errors', 'docker service logs traefik --tail 20 2>&1 | grep -i "error\\|api.extrator" | tail -5'),
        ('Recent API access logs', 'journalctl -u extrator-api --since "1 hour ago" --no-pager 2>&1 | tail -10'),
    ]

    for label, cmd in commands:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        print(f"\n  [{label}]")
        if out:
            print(f"    {out}")
        if err and 'error' in err.lower():
            print(f"    STDERR: {err[:200]}")

    ssh.close()
except Exception as e:
    print(f"  SSH ERROR: {e}")

print("\n" + "=" * 60)
print("DIAGNOSTICO COMPLETO")
print("=" * 60)
