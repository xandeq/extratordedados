"""Smoke tests for pipeline config endpoints — Phase 1.
Uses live-API fixtures from conftest.py (api_base, auth_headers).
Hits https://api.extratordedados.com.br — requires deploy before running.
"""
import requests


def test_get_config_unauthenticated_returns_401(api_base):
    """GET /api/admin/pipeline-config without token returns 401."""
    resp = requests.get(f"{api_base}/api/admin/pipeline-config", timeout=10)
    assert resp.status_code == 401


def test_get_config_admin_returns_keys(api_base, auth_headers):
    """GET /api/admin/pipeline-config with admin token returns expected keys."""
    resp = requests.get(
        f"{api_base}/api/admin/pipeline-config",
        headers=auth_headers,
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    for key in ('niches', 'region', 'hour', 'minute'):
        assert key in data, f"Missing key: {key}"
    assert isinstance(data['niches'], list)
    assert isinstance(data['hour'], int)


def test_put_config_updates_niches(api_base, auth_headers):
    """PUT /api/admin/pipeline-config with valid body returns {success: true}."""
    resp = requests.put(
        f"{api_base}/api/admin/pipeline-config",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"niches": ["restaurante", "academia"]},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
