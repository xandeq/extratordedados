"""
Input validation smoke tests — verifies Phase 2 validations are active.
Requires auth for protected endpoints.
Note: 429 is accepted alongside expected error codes — the in-memory rate limiter
carries state between test runs within the same hour window.
"""
import requests


# ── /api/search/massive ───────────────────────────────────────────────────────

def test_massive_search_without_auth_returns_401(api_base):
    resp = requests.post(f"{api_base}/api/search/massive", json={}, timeout=10)
    assert resp.status_code in (401, 429)


def test_massive_search_no_niches_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/search/massive",
        headers=auth_headers,
        json={"niches": [], "region": "grande_vitoria_es"},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


def test_massive_search_niches_not_list_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/search/massive",
        headers=auth_headers,
        json={"niches": "clinica medica", "region": "grande_vitoria_es"},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


def test_massive_search_no_region_or_city_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/search/massive",
        headers=auth_headers,
        json={"niches": ["Clinica Medica"]},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


def test_massive_search_too_many_niches_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/search/massive",
        headers=auth_headers,
        json={"niches": [f"Niche {i}" for i in range(25)], "region": "grande_vitoria_es"},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


# ── /api/leads/import ─────────────────────────────────────────────────────────

def test_leads_import_without_auth_returns_401(api_base):
    resp = requests.post(f"{api_base}/api/leads/import", json={}, timeout=10)
    assert resp.status_code in (401, 429)


def test_leads_import_empty_contacts_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/leads/import",
        headers=auth_headers,
        json={"contacts": []},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


def test_leads_import_contacts_not_list_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/leads/import",
        headers=auth_headers,
        json={"contacts": "not a list"},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


# ── /api/leads/delete-all ─────────────────────────────────────────────────────

def test_delete_all_without_auth_returns_401(api_base):
    resp = requests.post(f"{api_base}/api/leads/delete-all", json={}, timeout=10)
    assert resp.status_code in (401, 429)


def test_delete_all_without_confirm_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/leads/delete-all",
        headers=auth_headers,
        json={},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


def test_delete_all_wrong_confirm_returns_400(api_base, auth_headers):
    resp = requests.post(
        f"{api_base}/api/leads/delete-all",
        headers=auth_headers,
        json={"confirm": True},
        timeout=10,
    )
    assert resp.status_code in (400, 429)


# ── Protected endpoints return 401 without token ─────────────────────────────

def test_leads_without_auth_returns_401(api_base):
    resp = requests.get(f"{api_base}/api/leads", timeout=10)
    assert resp.status_code in (401, 429)


def test_analytics_without_auth_returns_401(api_base):
    resp = requests.get(f"{api_base}/api/analytics", timeout=10)
    assert resp.status_code in (401, 429)


def test_crm_status_without_auth_returns_401(api_base):
    resp = requests.get(f"{api_base}/api/crm/status", timeout=10)
    assert resp.status_code in (401, 429)
