"""Test batch scraping API endpoints"""
import sys
import json
import ssl
import http.client
import time

sys.stdout.reconfigure(encoding='utf-8')

API_HOST = 'api.extratordedados.com.br'
ctx = ssl.create_default_context()

def api(method, path, body=None, token=None):
    conn = http.client.HTTPSConnection(API_HOST, 443, timeout=30, context=ctx)
    headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode('utf-8')
    conn.close()
    return resp.status, data

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} - {detail}")

print("=" * 60)
print("BATCH SCRAPING API TESTS")
print("=" * 60)

# 1. Login
print("\n1. AUTHENTICATION")
status, body = api('POST', '/api/login', {'username': 'admin', 'password': '1982Xandeq1982#'})
data = json.loads(body)
token = data.get('token')
check("Login returns 200", status == 200)
check("Login returns token", token is not None)

# 2. Health (verify tables created)
print("\n2. HEALTH CHECK")
status, body = api('GET', '/api/health')
check("Health returns 200", status == 200)

# 3. Create batch with test URLs
print("\n3. CREATE BATCH")
test_urls = [
    'https://httpbin.org',
    'https://example.com',
    'https://www.python.org',
]
status, body = api('POST', '/api/batch', {
    'name': 'Test Batch API',
    'urls': test_urls,
}, token=token)
print(f"  Raw response: status={status}, body={body[:300]}")
if not body:
    print("  ERROR: Empty response body!")
    data = {}
    batch_id = None
else:
    data = json.loads(body)
    batch_id = data.get('batch_id')
check("Create batch returns 200", status == 200, f"got {status}: {body[:200]}")
check("Returns batch_id", batch_id is not None, f"data: {data}")
check("Returns total_urls", data.get('total_urls') == 3)
check("Status is processing", data.get('status') == 'processing')
print(f"  Batch ID: {batch_id}")

# 4. Test with Apify-format JSON
print("\n4. CREATE BATCH (APIFY FORMAT)")
apify_urls = [
    {"website": "https://httpbin.org"},
    {"website": "https://example.com"},
]
status, body = api('POST', '/api/batch', {
    'name': 'Test Apify Format',
    'urls': apify_urls,
}, token=token)
print(f"  Raw response: status={status}, body={body[:300]}")
data2 = json.loads(body) if body else {}
batch_id_2 = data2.get('batch_id')
check("Apify format batch returns 200", status == 200, f"got {status}: {body[:200]}")
check("Apify format returns batch_id", batch_id_2 is not None)
check("Apify format total_urls=2", data2.get('total_urls') == 2)

# 5. List batches
print("\n5. LIST BATCHES")
status, body = api('GET', '/api/batch', token=token)
data = json.loads(body)
batches = data.get('batches', [])
check("List batches returns 200", status == 200)
check("Batches is array", isinstance(batches, list))
check("At least 2 batches", len(batches) >= 2, f"got {len(batches)}")

# 6. Poll progress
print("\n6. BATCH PROGRESS (polling)")
if batch_id:
    for i in range(15):
        status, body = api('GET', f'/api/batch/{batch_id}/progress', token=token)
        progress = json.loads(body)
        pct = f"{progress.get('processed_urls', 0)}/{progress.get('total_urls', 0)}"
        leads = progress.get('total_leads', 0)
        st = progress.get('status', '?')
        print(f"  Poll {i+1}: {st} - {pct} URLs, {leads} leads")
        if st in ('completed', 'failed'):
            break
        time.sleep(3)

    check("Batch completed", st == 'completed', f"final status: {st}")
    check("All URLs processed", progress.get('processed_urls') == progress.get('total_urls'))

# 7. Get batch details
print("\n7. BATCH DETAILS")
if batch_id:
    status, body = api('GET', f'/api/batch/{batch_id}', token=token)
    data = json.loads(body)
    leads = data.get('leads', [])
    check("Get batch returns 200", status == 200)
    check("Returns leads array", isinstance(leads, list))
    check("Has leads", len(leads) > 0, f"got {len(leads)} leads")
    if leads:
        lead = leads[0]
        check("Lead has email", 'email' in lead)
        check("Lead has company_name", 'company_name' in lead)
        check("Lead has phone", 'phone' in lead)
        check("Lead has website", 'website' in lead)
        print(f"  Sample lead: {json.dumps(lead, ensure_ascii=False)[:200]}")

# 8. Export CSV
print("\n8. EXPORT CSV")
if batch_id:
    conn = http.client.HTTPSConnection(API_HOST, 443, timeout=15, context=ctx)
    conn.request('GET', f'/api/batch/{batch_id}/export?format=csv',
                 headers={'Authorization': f'Bearer {token}', 'User-Agent': 'Mozilla/5.0'})
    resp = conn.getresponse()
    csv_data = resp.read().decode('utf-8')
    ct = resp.getheader('Content-Type', '')
    cd = resp.getheader('Content-Disposition', '')
    conn.close()

    check("CSV export returns 200", resp.status == 200)
    check("Content-Type is text/csv", 'text/csv' in ct)
    check("Has attachment", 'attachment' in cd)
    check("CSV has CRM header", csv_data.startswith('Nome,Email,Telefone,WhatsApp,Empresa'))
    print(f"  CSV Preview: {csv_data[:200]}")

# 9. Export JSON
print("\n9. EXPORT JSON")
if batch_id:
    status, body = api('GET', f'/api/batch/{batch_id}/export?format=json', token=token)
    check("JSON export returns 200", status == 200)
    try:
        json_data = json.loads(body)
        check("JSON is valid array", isinstance(json_data, list))
    except:
        check("JSON is valid", False, "invalid JSON")

# 10. Export Text
print("\n10. EXPORT TEXT")
if batch_id:
    conn = http.client.HTTPSConnection(API_HOST, 443, timeout=15, context=ctx)
    conn.request('GET', f'/api/batch/{batch_id}/export?format=text',
                 headers={'Authorization': f'Bearer {token}', 'User-Agent': 'Mozilla/5.0'})
    resp = conn.getresponse()
    text_data = resp.read().decode('utf-8')
    conn.close()
    check("Text export returns 200", resp.status == 200)
    check("Text has content", len(text_data) > 0)
    print(f"  Text Preview: {text_data[:200]}")

# 11. Delete batch (use batch_id_2 to keep batch_id for inspection)
print("\n11. DELETE BATCH")
if batch_id_2:
    # Wait for batch 2 to finish first
    for i in range(10):
        status, body = api('GET', f'/api/batch/{batch_id_2}/progress', token=token)
        progress = json.loads(body)
        if progress.get('status') in ('completed', 'failed'):
            break
        time.sleep(3)

    status, body = api('DELETE', f'/api/batch/{batch_id_2}', token=token)
    check("Delete batch returns 200", status == 200, f"got {status}: {body[:100]}")

    # Verify deletion
    status, body = api('GET', f'/api/batch/{batch_id_2}', token=token)
    check("Deleted batch returns 404", status == 404)

# 12. Unauthorized access
print("\n12. UNAUTHORIZED ACCESS")
status, body = api('GET', '/api/batch')
check("No-token returns 401", status == 401)
status, body = api('POST', '/api/batch', {'name': 'test', 'urls': ['https://example.com']})
check("Create batch without token returns 401", status == 401)

# 13. Validation
print("\n13. VALIDATION")
status, body = api('POST', '/api/batch', {'urls': ['https://example.com']}, token=token)
check("Missing name returns 400", status == 400)
status, body = api('POST', '/api/batch', {'name': 'test'}, token=token)
check("Missing urls returns 400", status == 400)

# 14. Existing endpoints still work
print("\n14. LEGACY ENDPOINTS")
status, body = api('GET', '/api/results', token=token)
check("Legacy /api/results still works", status == 200)

# Summary
print("\n" + "=" * 60)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 60)

if failed == 0:
    print("\nALL TESTS PASSED!")
else:
    print(f"\n{failed} test(s) failed - review above")
