"""
Pytest configuration for smoke tests against the live API.
Run: pytest tests/ -v
"""
import json
import subprocess
import pytest

API_BASE = "https://api.extratordedados.com.br"


def _load_credentials():
    """Load test credentials from AWS Secrets Manager."""
    try:
        result = subprocess.run(
            ["python", "-m", "awscli", "secretsmanager", "get-secret-value",
             "--secret-id", "extratordedados/prod",
             "--query", "SecretString", "--output", "text"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return json.loads(result.stdout.strip())
    except Exception:
        pass
    return {}


@pytest.fixture(scope="session")
def api_base():
    return API_BASE


@pytest.fixture(scope="session")
def credentials():
    return _load_credentials()


@pytest.fixture(scope="session")
def auth_token(api_base, credentials):
    """Get a valid auth token by logging in as admin."""
    import requests
    admin_pass = credentials.get("ADMIN_PASSWORD", "")
    if not admin_pass:
        pytest.skip("ADMIN_PASSWORD not available in AWS SM")
    resp = requests.post(
        f"{api_base}/api/login",
        json={"username": "admin", "password": admin_pass},
        timeout=10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="session")
def client_token(api_base, credentials):
    """Get auth token for a test client user (role='client')."""
    import requests
    client_pass = credentials.get("CLIENT_TEST_PASSWORD", "")
    if not client_pass:
        pytest.skip("CLIENT_TEST_PASSWORD not available in AWS SM — client tests require a seeded test user")
    resp = requests.post(
        f"{api_base}/api/login",
        json={"username": "test_client", "password": client_pass},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip(f"Client login failed (test_client user may not exist yet): {resp.text}")
    return resp.json()["token"]
