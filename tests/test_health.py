"""
Smoke tests — health check and basic API availability.
No auth required.
"""
import requests


def test_health_returns_200(api_base):
    resp = requests.get(f"{api_base}/api/health", timeout=10)
    assert resp.status_code == 200


def test_health_status_ok(api_base):
    resp = requests.get(f"{api_base}/api/health", timeout=10)
    body = resp.json()
    assert body.get("status") == "ok"


def test_health_db_postgresql(api_base):
    resp = requests.get(f"{api_base}/api/health", timeout=10)
    body = resp.json()
    assert body.get("db") == "postgresql"


def test_health_has_timestamp(api_base):
    resp = requests.get(f"{api_base}/api/health", timeout=10)
    body = resp.json()
    assert "timestamp" in body


def test_404_returns_json_or_html(api_base):
    """Unknown endpoint should not return 500."""
    resp = requests.get(f"{api_base}/api/this-endpoint-does-not-exist", timeout=10)
    assert resp.status_code in (404, 405)
