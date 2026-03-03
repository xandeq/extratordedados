import ssl
import socket
import json
import http.client
import sys

sys.stdout.reconfigure(encoding='utf-8')

host = 'api.extratordedados.com.br'

# Test 1: Raw socket connection to port 443
print("=== Test 1: TCP connection to port 443 ===")
try:
    s = socket.create_connection((host, 443), timeout=10)
    print(f"TCP connected to {host}:443 OK")
    s.close()
except Exception as e:
    print(f"TCP failed: {e}")

# Test 2: TLS handshake
print("\n=== Test 2: TLS handshake ===")
try:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    s = socket.create_connection((host, 443), timeout=10)
    ss = context.wrap_socket(s, server_hostname=host)
    cert = ss.getpeercert(binary_form=False)
    print(f"TLS handshake OK")
    print(f"Protocol: {ss.version()}")
    print(f"Cipher: {ss.cipher()}")
    if cert:
        print(f"Subject: {cert.get('subject')}")
    ss.close()
except Exception as e:
    print(f"TLS failed: {e}")

# Test 3: HTTPS request
print("\n=== Test 3: HTTPS GET /api/health ===")
try:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, 443, timeout=10, context=context)
    conn.request('GET', '/api/health')
    resp = conn.getresponse()
    body = resp.read().decode('utf-8')
    print(f"Status: {resp.status}")
    print(f"Body: {body}")
    conn.close()
except Exception as e:
    print(f"HTTPS request failed: {e}")

# Test 4: HTTP request (should redirect)
print("\n=== Test 4: HTTP GET /api/health ===")
try:
    conn = http.client.HTTPConnection(host, 80, timeout=10)
    conn.request('GET', '/api/health')
    resp = conn.getresponse()
    body = resp.read().decode('utf-8')
    print(f"Status: {resp.status}")
    print(f"Location: {resp.getheader('Location')}")
    print(f"Body: {body[:100]}")
    conn.close()
except Exception as e:
    print(f"HTTP request failed: {e}")
