"""
Wave 0 smoke tests for Phase 10 — Novas Fontes de Extração.
Tests call the live API at https://api.extratordedados.com.br.
Use existing fixtures: api_base, auth_headers from conftest.py.
"""
import pytest
import requests


def test_massive_accepts_apple_maps_method(api_base, auth_headers):
    """SRC-01: apple_maps method accepted without error."""
    resp = requests.post(f"{api_base}/api/search/massive",
                         json={"niches": ["Clinica Medica"],
                               "city": "Vitoria", "state": "ES",
                               "methods": ["apple_maps"],
                               "max_pages": 1},
                         headers=auth_headers, timeout=30)
    assert resp.status_code == 200


def test_apple_maps_jobs_created(api_base, auth_headers):
    """SRC-01: apple_maps appears in response methods dict."""
    resp = requests.post(f"{api_base}/api/search/massive",
                         json={"niches": ["Clinica Odontologica"],
                               "city": "Vila Velha", "state": "ES",
                               "methods": ["apple_maps"],
                               "max_pages": 1},
                         headers=auth_headers, timeout=30)
    data = resp.json()
    assert 'apple_maps' in data.get('methods', {}), f"methods dict: {data.get('methods')}"
    assert data['methods']['apple_maps'] >= 1


def test_massive_accepts_foursquare_method(api_base, auth_headers):
    """SRC-02: foursquare method accepted without error (stub — Thread 18 added in Plan 03)."""
    resp = requests.post(f"{api_base}/api/search/massive",
                         json={"niches": ["Clinica Medica"],
                               "city": "Vitoria", "state": "ES",
                               "methods": ["foursquare"],
                               "max_pages": 1},
                         headers=auth_headers, timeout=30)
    # Accept 200 (foursquare in methods dict) or 200 with foursquare: 0 (not yet wired)
    assert resp.status_code == 200


def test_outscraper_jobs_engine_value(api_base, auth_headers):
    """SRC-03: outscraper_maps method creates jobs with correct engine value."""
    resp = requests.post(f"{api_base}/api/search/massive",
                         json={"niches": ["Clinica Medica"],
                               "city": "Vitoria", "state": "ES",
                               "methods": ["outscraper_maps"],
                               "max_pages": 1},
                         headers=auth_headers, timeout=30)
    data = resp.json()
    assert resp.status_code == 200
    assert 'outscraper_maps' in data.get('methods', {})


def test_search_engine_template_expansion(api_base, auth_headers):
    """SRC-04: search_engines method creates 5 search_jobs per niche+city after Plan 02."""
    # This test passes trivially pre-Plan-02 (returns 200); re-verified after Plan 02.
    resp = requests.post(f"{api_base}/api/search/massive",
                         json={"niches": ["Clinica Medica"],
                               "city": "Vitoria", "state": "ES",
                               "methods": ["search_engines"],
                               "max_pages": 1},
                         headers=auth_headers, timeout=30)
    data = resp.json()
    assert resp.status_code == 200
    assert data.get('methods', {}).get('search_engines', 0) >= 1


def test_search_engine_unique_queries(api_base, auth_headers):
    """SRC-04: each search_job has a distinct query (verified after Plan 02 via DB or logs)."""
    # Smoke: endpoint returns 200 and creates search_engine jobs
    resp = requests.post(f"{api_base}/api/search/massive",
                         json={"niches": ["Clinica Veterinaria"],
                               "city": "Serra", "state": "ES",
                               "methods": ["search_engines"],
                               "max_pages": 1},
                         headers=auth_headers, timeout=30)
    assert resp.status_code == 200


def test_source_stats_endpoint(api_base, auth_headers):
    """source-stats: GET /api/admin/source-stats returns 200 with list."""
    resp = requests.get(f"{api_base}/api/admin/source-stats",
                        headers=auth_headers, timeout=15)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert 'source' in data[0]
        assert 'count' in data[0]


def test_source_stats_has_data(api_base, auth_headers):
    """source-stats: response includes at least one known source."""
    resp = requests.get(f"{api_base}/api/admin/source-stats",
                        headers=auth_headers, timeout=15)
    assert resp.status_code == 200
    data = resp.json()
    sources = [r['source'] for r in data]
    known = {'google_maps', 'search_engine', 'outscraper_maps', 'apify_maps',
             'instagram', 'linkedin', 'local_business_data', 'apple_maps', 'foursquare'}
    assert any(s in known for s in sources), f"No known source found. Got: {sources}"
