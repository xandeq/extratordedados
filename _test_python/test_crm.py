import requests
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ALEXANDREQUEIROZ_API = 'https://api.alexandrequeiroz.com.br'
ALEXANDREQUEIROZ_EMAIL = 'admin@alexandrequeiroz.com.br'
ALEXANDREQUEIROZ_PASSWORD = 'REDACTED_PASSWORD'

def test():
    print(f"Logging in to {ALEXANDREQUEIROZ_API}...")
    try:
        login_res = requests.post(
            f'{ALEXANDREQUEIROZ_API}/api/v1/auth/login',
            json={'email': ALEXANDREQUEIROZ_EMAIL, 'password': ALEXANDREQUEIROZ_PASSWORD},
            verify=False
        )
        print(f"Login Status: {login_res.status_code}")

        if login_res.status_code != 200:
            print(f"Login Failed: {login_res.text}")
            return

        token = login_res.json().get('token')
        print(f"Token length: {len(token) if token else 0}")

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Test 1: GET customers
        print("\nTesting GET customers...")
        get_res = requests.get(
            f'{ALEXANDREQUEIROZ_API}/api/v1/customers',
            headers=headers,
            params={'search': 'test@test.com', 'pageSize': 1},
            verify=False
        )
        print(f"GET Status: {get_res.status_code}")

        # Test 2: POST customer
        print("\nTesting POST customer...")
        post_res = requests.post(
            f'{ALEXANDREQUEIROZ_API}/api/v1/customers',
            headers=headers,
            json={
                'name': 'Test Extrator',
                'companyName': 'Test Extrator',
                'email': 'test@extrator.com.br',
            },
            verify=False
        )
        print(f"POST Status: {post_res.status_code}")
        print(f"POST Response: {post_res.text}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test()
