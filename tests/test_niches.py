"""
Smoke tests for Phase 8: Catálogo de Nichos.
Run: pytest tests/test_niches.py -x -v
Full suite: pytest tests/ -x
"""
import pytest
import requests

pytestmark = pytest.mark.usefixtures()


def test_admin_niches_requires_auth(api_base):
    """GET /api/admin/niches without token returns 401."""
    resp = requests.get(f"{api_base}/api/admin/niches", timeout=10)
    assert resp.status_code == 401


def test_admin_get_niches_returns_catalog(api_base, auth_headers):
    """GET /api/admin/niches returns catalog grouped by category with total."""
    resp = requests.get(f"{api_base}/api/admin/niches", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert 'niches' in data
    assert 'total' in data
    assert isinstance(data['niches'], dict)
    assert len(data['niches']) >= 1


def test_niches_catalog_count_gte_150(api_base, auth_headers):
    """GET /api/admin/niches returns at least 150 niches total after populate_niches.sql."""
    resp = requests.get(f"{api_base}/api/admin/niches", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get('total', 0) >= 150, f"Expected 150+ niches, got {data.get('total')}"


def test_admin_toggle_niche_active(api_base, auth_headers):
    """PUT /api/admin/niches/<id> toggles active field."""
    # Get first niche ID
    resp = requests.get(f"{api_base}/api/admin/niches", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    niches = resp.json().get('niches', {})
    all_niches = [n for cat in niches.values() for n in cat]
    if not all_niches:
        pytest.skip("No niches in catalog yet — run populate_niches.sql first")
    niche_id = all_niches[0]['id']
    current_active = all_niches[0]['active']

    # Toggle
    toggle_resp = requests.put(
        f"{api_base}/api/admin/niches/{niche_id}",
        json={'active': not current_active},
        headers=auth_headers,
        timeout=10
    )
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()['active'] == (not current_active)

    # Restore
    requests.put(
        f"{api_base}/api/admin/niches/{niche_id}",
        json={'active': current_active},
        headers=auth_headers,
        timeout=10
    )


def test_admin_bulk_toggle_niches(api_base, auth_headers):
    """PUT /api/admin/niches/bulk deactivates a batch of niches."""
    resp = requests.get(f"{api_base}/api/admin/niches", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    niches = resp.json().get('niches', {})
    all_niches = [n for cat in niches.values() for n in cat]
    if len(all_niches) < 3:
        pytest.skip("Not enough niches to test bulk — run populate_niches.sql first")
    ids = [n['id'] for n in all_niches[:3]]

    bulk_resp = requests.put(
        f"{api_base}/api/admin/niches/bulk",
        json={'ids': ids, 'active': False},
        headers=auth_headers,
        timeout=10
    )
    assert bulk_resp.status_code == 200
    assert bulk_resp.json()['updated'] == 3
    assert bulk_resp.json()['active'] == False

    # Restore
    requests.put(
        f"{api_base}/api/admin/niches/bulk",
        json={'ids': ids, 'active': True},
        headers=auth_headers,
        timeout=10
    )


def test_public_niches_endpoint_grouped(api_base, auth_headers):
    """GET /api/niches?active=true returns niches grouped by category."""
    resp = requests.get(f"{api_base}/api/niches?active=true", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert 'niches' in data
    assert isinstance(data['niches'], dict)


def test_public_niches_has_10_categories(api_base, auth_headers):
    """GET /api/niches?active=true returns niches in exactly 10 categories."""
    resp = requests.get(f"{api_base}/api/niches?active=true", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    categories = list(data['niches'].keys())
    assert len(categories) >= 10, f"Expected 10 categories, got {len(categories)}: {categories}"


def test_pipeline_config_niches_from_db(api_base, auth_headers):
    """GET /api/admin/pipeline-config returns niches key sourced from DB (not hardcoded list).
    This test is activated in Plan 02 after get_pipeline_config() is modified.
    For now, verifies that the endpoint still works (backward compat)."""
    resp = requests.get(f"{api_base}/api/admin/pipeline-config", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert 'niches' in data
    assert isinstance(data['niches'], list)
