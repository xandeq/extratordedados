"""Test rate limiting specifically"""
import sys
import json
import ssl
import http.client
import time

sys.stdout.reconfigure(encoding='utf-8')

API_HOST = 'api.extratordedados.com.br'
context = ssl.create_default_context()

print("=== Rate Limit Test: POST /api/login (limit: 5/minute) ===\n")

for i in range(8):
    conn = http.client.HTTPSConnection(API_HOST, 443, timeout=10, context=context)
    body = json.dumps({'username': 'admin', 'password': '1982Xandeq1982#'})
    conn.request('POST', '/api/login', body=body, headers={
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0',
    })
    resp = conn.getresponse()
    data = resp.read().decode('utf-8')

    # Check all response headers
    headers_of_interest = {}
    for h, v in resp.getheaders():
        hl = h.lower()
        if 'rate' in hl or 'limit' in hl or 'retry' in hl or 'ratelimit' in hl:
            headers_of_interest[h] = v

    print(f"  Request {i+1}: status={resp.status}, headers={headers_of_interest}")
    if resp.status == 429:
        print(f"\n  RATE LIMITED at request {i+1}!")
        print(f"  Response: {data[:200]}")
        break
    conn.close()

print("\n=== Test complete ===")
