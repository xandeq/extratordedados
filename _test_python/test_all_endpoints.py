import requests
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE = 'https://api.extratordedados.com.br'

# Test 1: Health
print("=== 1. Health Check ===")
r = requests.get(f'{BASE}/api/health', timeout=15)
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text}")

# Test 2: Login
print("\n=== 2. Login ===")
r = requests.post(f'{BASE}/api/login', json={
    'username': 'admin',
    'password': '1982Xandeq1982#'
}, timeout=15)
print(f"  Status: {r.status_code}")
data = r.json()
print(f"  Body: {json.dumps(data)}")
token = data.get('token', '')

# Test 3: Scrape
print("\n=== 3. Scrape (extratordedados.com.br) ===")
r = requests.post(f'{BASE}/api/scrape', json={
    'url': 'https://www.python.org',
    'depth': 1
}, headers={'Authorization': f'Bearer {token}'}, timeout=30)
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text[:300]}")
scrape_data = r.json()
job_id = scrape_data.get('job_id')

# Test 4: Results list
print("\n=== 4. Results List ===")
r = requests.get(f'{BASE}/api/results',
    headers={'Authorization': f'Bearer {token}'}, timeout=15)
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text[:300]}")

# Test 5: Results by job_id
if job_id:
    print(f"\n=== 5. Results for Job {job_id} ===")
    r = requests.get(f'{BASE}/api/results/{job_id}',
        headers={'Authorization': f'Bearer {token}'}, timeout=15)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:300]}")

# Test 6: Unauthorized access
print("\n=== 6. Unauthorized Access ===")
r = requests.get(f'{BASE}/api/results', timeout=15)
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text}")

print("\n=== ALL TESTS COMPLETE ===")
