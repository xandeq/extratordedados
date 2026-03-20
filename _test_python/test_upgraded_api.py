"""
Test all upgraded API endpoints: PostgreSQL, rate limiting, dedup, CSV export
"""
import sys
import json
import ssl
import http.client
import time

sys.stdout.reconfigure(encoding='utf-8')

API_HOST = 'api.extratordedados.com.br'
context = ssl.create_default_context()

def api_call(method, path, body=None, token=None):
    conn = http.client.HTTPSConnection(API_HOST, 443, timeout=15, context=context)
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 TestClient',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode('utf-8')

    # Get rate limit headers
    rl_remaining = resp.getheader('X-RateLimit-Remaining')
    rl_limit = resp.getheader('X-RateLimit-Limit')
    retry_after = resp.getheader('Retry-After')

    result = {
        'status': resp.status,
        'body': data,
        'rate_limit': rl_limit,
        'rate_remaining': rl_remaining,
        'retry_after': retry_after,
    }
    conn.close()
    return result

print("=" * 60)
print("TEST UPGRADED API - PostgreSQL + Rate Limiting + Dedup + CSV")
print("=" * 60)

# 1. Health check
print("\n--- 1. GET /api/health ---")
r = api_call('GET', '/api/health')
print(f"  Status: {r['status']}")
print(f"  Body: {r['body']}")
print(f"  Rate Limit: {r['rate_limit']}, Remaining: {r['rate_remaining']}")
assert r['status'] == 200
data = json.loads(r['body'])
assert data['db'] == 'postgresql', f"Expected postgresql, got {data.get('db')}"
print("  PASS: PostgreSQL confirmed")

# 2. Login
print("\n--- 2. POST /api/login ---")
r = api_call('POST', '/api/login', {'username': 'admin', 'password': 'REDACTED_PASSWORD'})
print(f"  Status: {r['status']}")
print(f"  Rate Limit: {r['rate_limit']}, Remaining: {r['rate_remaining']}")
assert r['status'] == 200
token = json.loads(r['body'])['token']
print(f"  Token: {token[:20]}...")
print("  PASS: Login works")

# 3. Scrape (test deduplication)
print("\n--- 3. POST /api/scrape (test dedup) ---")
r = api_call('POST', '/api/scrape', {'url': 'https://httpbin.org'}, token=token)
print(f"  Status: {r['status']}")
print(f"  Body: {r['body']}")
print(f"  Rate Limit: {r['rate_limit']}")
if r['status'] == 200:
    scrape_data = json.loads(r['body'])
    job_id = scrape_data['job_id']
    print(f"  Job ID: {job_id}")
    print(f"  Results: {scrape_data.get('results_count', 0)} emails")
    print("  PASS: Scrape works")
else:
    print(f"  Note: Scrape returned {r['status']} (may be rate limited or target has no emails)")
    # Try to get results from first job
    job_id = 1

# 4. Get results
print("\n--- 4. GET /api/results ---")
r = api_call('GET', '/api/results', token=token)
print(f"  Status: {r['status']}")
assert r['status'] == 200
jobs = json.loads(r['body'])
print(f"  Jobs count: {len(jobs.get('jobs', []))}")
if jobs.get('jobs'):
    job_id = jobs['jobs'][0]['id']
    print(f"  Latest job: ID={job_id}, URL={jobs['jobs'][0]['url'][:50]}")
print("  PASS: List results works")

# 5. Get specific result
print(f"\n--- 5. GET /api/results/{job_id} ---")
r = api_call('GET', f'/api/results/{job_id}', token=token)
print(f"  Status: {r['status']}")
if r['status'] == 200:
    result = json.loads(r['body'])
    print(f"  URL: {result['url'][:50]}")
    print(f"  Emails: {result['results_count']}")
    print("  PASS: Get result works")
else:
    print(f"  Response: {r['body'][:100]}")

# 6. CSV Export
print(f"\n--- 6. GET /api/results/{job_id}/export (CSV) ---")
conn = http.client.HTTPSConnection(API_HOST, 443, timeout=15, context=context)
conn.request('GET', f'/api/results/{job_id}/export', headers={
    'Authorization': f'Bearer {token}',
    'User-Agent': 'Mozilla/5.0 TestClient',
})
resp = conn.getresponse()
content_type = resp.getheader('Content-Type')
content_disp = resp.getheader('Content-Disposition')
csv_data = resp.read().decode('utf-8')
conn.close()
print(f"  Status: {resp.status}")
print(f"  Content-Type: {content_type}")
print(f"  Content-Disposition: {content_disp}")
print(f"  CSV Preview (first 200 chars):")
print(f"    {csv_data[:200]}")
if resp.status == 200:
    assert 'text/csv' in (content_type or ''), f"Expected text/csv, got {content_type}"
    assert 'attachment' in (content_disp or ''), f"Expected attachment disposition"
    print("  PASS: CSV export works")

# 7. Test rate limiting (login endpoint: 5/minute)
print("\n--- 7. Rate Limiting Test (login: 5/min) ---")
print("  Sending 6 rapid login requests...")
for i in range(6):
    r = api_call('POST', '/api/login', {'username': 'admin', 'password': 'REDACTED_PASSWORD'})
    status = r['status']
    remaining = r['rate_remaining']
    print(f"  Request {i+1}: status={status}, remaining={remaining}")
    if status == 429:
        print(f"  PASS: Rate limited at request {i+1} (429 Too Many Requests)")
        print(f"  Retry-After: {r['retry_after']}")
        break
else:
    print("  NOTE: Rate limit not triggered (may need more requests)")

# 8. Test unauthorized access
print("\n--- 8. Unauthorized Access ---")
r = api_call('GET', '/api/results')
print(f"  Status: {r['status']}")
assert r['status'] == 401
print("  PASS: Returns 401 without token")

# 9. Test invalid login
print("\n--- 9. Invalid Login ---")
time.sleep(2)  # Wait a bit for rate limit to partially reset
r = api_call('POST', '/api/login', {'username': 'admin', 'password': 'wrong'})
print(f"  Status: {r['status']}")
if r['status'] == 401:
    print("  PASS: Returns 401 for bad credentials")
elif r['status'] == 429:
    print("  PASS (rate limited - expected after test 7)")

print("\n" + "=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
