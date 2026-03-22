"""
Auth endpoint smoke tests — login, logout, token validation.
"""
import requests


# ── /api/login ────────────────────────────────────────────────────────────────

def test_login_missing_body_returns_400(api_base):
    # Werkzeug >=2.3 returns 415 (no Content-Type); 429 if rate-limited between runs
    resp = requests.post(f"{api_base}/api/login", timeout=10)
    assert resp.status_code in (400, 415, 429)


def test_login_wrong_credentials_returns_401(api_base):
    resp = requests.post(
        f"{api_base}/api/login",
        json={"username": "admin", "password": "definitely_wrong_password_xyz_123"},
        timeout=10,
    )
    assert resp.status_code in (401, 429)


def test_login_missing_password_returns_400(api_base):
    resp = requests.post(
        f"{api_base}/api/login",
        json={"username": "admin"},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


def test_login_missing_username_returns_400(api_base):
    resp = requests.post(
        f"{api_base}/api/login",
        json={"password": "somepass"},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


def test_login_success_returns_token(auth_token):
    """Uses the session-scoped auth_token fixture — verifies token is non-empty."""
    assert auth_token and len(auth_token) > 10


# ── /api/me ───────────────────────────────────────────────────────────────────

def test_me_without_token_returns_401(api_base):
    resp = requests.get(f"{api_base}/api/me", timeout=10)
    assert resp.status_code in (401, 429)


def test_me_with_invalid_token_returns_401(api_base):
    resp = requests.get(
        f"{api_base}/api/me",
        headers={"Authorization": "Bearer invalidtoken000"},
        timeout=10,
    )
    assert resp.status_code in (401, 429)


def test_me_with_valid_token_returns_200(api_base, auth_headers):
    resp = requests.get(f"{api_base}/api/me", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert "username" in body


# ── /api/logout ───────────────────────────────────────────────────────────────

def test_logout_without_token_returns_400(api_base):
    resp = requests.post(f"{api_base}/api/logout", timeout=10)
    assert resp.status_code in (400, 429)


def test_logout_with_invalid_token_returns_200(api_base):
    """Logout with unknown token is idempotent (DELETE 0 rows, no error)."""
    resp = requests.post(
        f"{api_base}/api/logout",
        headers={"Authorization": "Bearer aaabbbccc111"},
        timeout=10,
    )
    assert resp.status_code == 200
