import http.client
import ssl
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 60)
print("CHECK HOSTGATOR RESPONSE HEADERS")
print("=" * 60)

# Check HTTPS response headers from HostGator
print("\n--- HTTPS extratordedados.com.br/login/ ---")
try:
    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection('extratordedados.com.br', 443, timeout=10, context=context)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    conn.request('GET', '/login/', headers=headers)
    resp = conn.getresponse()
    print(f"  Status: {resp.status}")
    print(f"  All headers:")
    for h, v in resp.getheaders():
        print(f"    {h}: {v}")
    body = resp.read().decode('utf-8', errors='replace')
    # Check for Content-Security-Policy or other restrictive headers
    csp = resp.getheader('Content-Security-Policy')
    if csp:
        print(f"\n  CSP FOUND: {csp}")
    else:
        print(f"\n  No Content-Security-Policy header")

    # Check if body has the correct API URL
    if 'api.extratordedados.com.br' in body:
        print(f"  API URL found in HTML: YES")
    else:
        print(f"  API URL found in HTML: NO (checking JS chunks...)")

    # Check for meta tags that might restrict connections
    if 'meta http-equiv' in body.lower():
        import re
        metas = re.findall(r'<meta[^>]*http-equiv[^>]*>', body, re.IGNORECASE)
        for m in metas:
            print(f"  Meta tag: {m}")

    conn.close()
except Exception as e:
    print(f"  ERROR: {e}")

# Check HTTP response headers
print("\n--- HTTP extratordedados.com.br/login/ ---")
try:
    conn = http.client.HTTPConnection('extratordedados.com.br', 80, timeout=10)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    conn.request('GET', '/login/', headers=headers)
    resp = conn.getresponse()
    print(f"  Status: {resp.status}")
    print(f"  All headers:")
    for h, v in resp.getheaders():
        print(f"    {h}: {v}")
    conn.close()
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 60)
