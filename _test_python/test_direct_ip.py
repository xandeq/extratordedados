import ssl
import socket
import http.client
import sys

sys.stdout.reconfigure(encoding='utf-8')

ip = '185.173.110.180'
host = 'api.extratordedados.com.br'

# Test direct to VPS IP on port 80
print("=== Test HTTP direct to VPS IP ===")
try:
    conn = http.client.HTTPConnection(ip, 80, timeout=10)
    conn.request('GET', '/api/health', headers={'Host': host})
    resp = conn.getresponse()
    body = resp.read().decode('utf-8')
    print(f"Status: {resp.status}")
    print(f"Location: {resp.getheader('Location')}")
    print(f"Body: {body[:200]}")
    conn.close()
except Exception as e:
    print(f"Failed: {e}")

# Test direct to VPS IP on port 443
print("\n=== Test HTTPS direct to VPS IP ===")
try:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(ip, 443, timeout=10, context=context)
    conn.request('GET', '/api/health', headers={'Host': host})
    resp = conn.getresponse()
    body = resp.read().decode('utf-8')
    print(f"Status: {resp.status}")
    print(f"Body: {body[:200]}")
    conn.close()
except Exception as e:
    print(f"Failed: {e}")

# Check what DNS resolves to from Python
print("\n=== DNS Resolution ===")
try:
    ips = socket.getaddrinfo(host, 443)
    for info in ips:
        print(f"  {info[4]}")
except Exception as e:
    print(f"DNS failed: {e}")

# Flush DNS and try
print("\n=== Test port 8000 directly (bypassing Traefik) ===")
try:
    conn = http.client.HTTPConnection(ip, 8000, timeout=10)
    conn.request('GET', '/api/health')
    resp = conn.getresponse()
    body = resp.read().decode('utf-8')
    print(f"Status: {resp.status}")
    print(f"Body: {body[:200]}")
    conn.close()
except Exception as e:
    print(f"Failed: {e}")
