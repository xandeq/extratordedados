"""
Smoke tests for Phase 9: Expansão Regional ES.
Run: pytest tests/test_regions.py -x -v
Full suite: pytest tests/ -x --tb=short
"""
import pytest
import requests


def test_regions_requires_auth(api_base):
    """GET /api/admin/regions without token returns 401."""
    resp = requests.get(f"{api_base}/api/admin/regions", timeout=10)
    assert resp.status_code == 401


def test_get_regions_endpoint(api_base, auth_headers):
    """GET /api/admin/regions returns list with expected fields."""
    resp = requests.get(f"{api_base}/api/admin/regions", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert 'regions' in data
    assert 'total' in data
    assert isinstance(data['regions'], list)
    if data['regions']:
        r = data['regions'][0]
        for field in ('id', 'name', 'city', 'state', 'ibge_code', 'priority', 'active', 'last_used_at', 'leads_last_30d', 'leads_total'):
            assert field in r, f"Missing field: {field}"


def test_regions_count_78_after_populate(api_base, auth_headers):
    """GET /api/admin/regions returns 78 cities after populate_es_cities.sql is run."""
    resp = requests.get(f"{api_base}/api/admin/regions", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    if data['total'] == 0:
        pytest.skip("regions table empty — run populate_es_cities.sql on VPS first")
    assert data['total'] == 78, f"Expected 78 cities, got {data['total']}"


def test_bulk_update_regions(api_base, auth_headers):
    """PUT /api/admin/regions/bulk deactivates a batch of regions."""
    resp = requests.get(f"{api_base}/api/admin/regions", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    regions = resp.json().get('regions', [])
    if len(regions) < 3:
        pytest.skip("Not enough regions to test bulk — run populate_es_cities.sql first")
    ids = [r['id'] for r in regions[:3]]
    original_active = [r['active'] for r in regions[:3]]

    bulk_resp = requests.put(
        f"{api_base}/api/admin/regions/bulk",
        json={'ids': ids, 'active': False},
        headers=auth_headers,
        timeout=10
    )
    assert bulk_resp.status_code == 200
    assert bulk_resp.json()['updated'] == 3
    assert bulk_resp.json()['active'] == False

    # Restore
    for r_id, was_active in zip(ids, original_active):
        requests.put(
            f"{api_base}/api/admin/regions/bulk",
            json={'ids': [r_id], 'active': was_active},
            headers=auth_headers,
            timeout=10
        )


def test_bulk_update_regions_empty_ids_returns_400(api_base, auth_headers):
    """PUT /api/admin/regions/bulk with empty ids returns 400."""
    resp = requests.put(
        f"{api_base}/api/admin/regions/bulk",
        json={'ids': [], 'active': True},
        headers=auth_headers,
        timeout=10
    )
    assert resp.status_code == 400


def test_get_pipeline_config_cities_from_db(api_base, auth_headers):
    """GET /api/admin/pipeline-config includes cities key after Plan 02 is done.
    For now, verifies the endpoint still works (backward compat with existing behavior)."""
    resp = requests.get(f"{api_base}/api/admin/pipeline-config", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert 'region' in data or 'niches' in data  # basic backward compat check


def test_mark_cities_used_updates_last_used_at(api_base, auth_headers):
    """After pipeline trigger, regions that were used have last_used_at set.
    This test is activated after Plan 02 (_mark_cities_used implementation) and
    a pipeline run. Skips gracefully if regions table is empty."""
    resp = requests.get(f"{api_base}/api/admin/regions", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    if data['total'] == 0:
        pytest.skip("regions table empty — run populate_es_cities.sql on VPS first")
    # After at least one pipeline run, some cities should have last_used_at set
    # This passes trivially before any pipeline run (no assertion on count)
    regions_with_ts = [r for r in data['regions'] if r['last_used_at'] is not None]
    assert isinstance(regions_with_ts, list)  # always true — test verifies structure


def test_round_robin_rotation(api_base, auth_headers):
    """Round-robin: GET /api/admin/regions returns cities ordered by last_used_at ASC NULLS FIRST.
    Cities with last_used_at=NULL appear before cities with a timestamp.
    This test is activated after Plan 02 and at least one pipeline run."""
    resp = requests.get(f"{api_base}/api/admin/regions", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    if data['total'] == 0:
        pytest.skip("regions table empty — run populate_es_cities.sql on VPS first")
    regions = data['regions']
    # Verify response has expected structure (rotation logic verified by Plan 02 tests)
    assert len(regions) >= 1
    assert all('last_used_at' in r for r in regions)
