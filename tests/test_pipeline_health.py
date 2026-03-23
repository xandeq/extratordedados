"""Smoke tests for GET /api/admin/pipeline/health — Phase 1.
Uses live-API fixtures from conftest.py (api_base, auth_headers).
Hits https://api.extratordedados.com.br — requires deploy before running.
"""
import requests


def test_health_unauthenticated_returns_401(api_base):
    """GET /api/admin/pipeline/health without token returns 401."""
    resp = requests.get(f"{api_base}/api/admin/pipeline/health", timeout=10)
    assert resp.status_code == 401


def test_health_response_has_required_keys(api_base, auth_headers):
    """GET /api/admin/pipeline/health with admin token returns expected shape."""
    resp = requests.get(
        f"{api_base}/api/admin/pipeline/health",
        headers=auth_headers,
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'last_run' in data
    assert 'next_scheduled' in data
    assert 'stats_30d' in data
    assert 'scheduler_running' in data
    stats = data['stats_30d']
    for key in ('total', 'successful', 'avg_leads', 'max_leads'):
        assert key in stats, f"Missing stats_30d key: {key}"
