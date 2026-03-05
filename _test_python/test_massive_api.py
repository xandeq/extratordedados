import requests
import time
import sys

API_URL = "https://api.extratordedados.com.br"

print("Logging in...")
login_res = requests.post(f"{API_URL}/api/login", json={"username": "admin", "password": "REDACTED_PASSWORD"})
if login_res.status_code != 200:
    print(f"Login failed: {login_res.text}")
    sys.exit(1)

token = login_res.json().get("token") or login_res.json().get("access_token")
if not token:
    print(f"No token received, JSON: {login_res.json()}")
    sys.exit(1)

headers = {"Authorization": f"Bearer {token}"}

payload = {
    "niches": ["Restaurante", "Imobiliária"],
    "region": "grande_vitoria_es",
    "methods": ["api_enrichment", "google_maps", "instagram", "linkedin"],
    "max_pages": 1
}

print(f"Testing massive search API at {API_URL}/api/search/massive...")
response = requests.post(f"{API_URL}/api/search/massive", json=payload, headers=headers)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")

if response.status_code == 200:
    batch_id = response.json().get("batch_id")
    print(f"\nBatch ID: {batch_id}")

    print("\nChecking progress...")
    for i in range(3):
        time.sleep(5)
        prog_res = requests.get(f"{API_URL}/api/batch/{batch_id}/progress", headers=headers)
        print(f"\n--- Progress Check {i+1} ---")
        print(f"Status Code: {prog_res.status_code}")
        try:
            print(f"Progress Data: {prog_res.json()}")
        except Exception as e:
            print(f"Raw Response: {prog_res.text}")
