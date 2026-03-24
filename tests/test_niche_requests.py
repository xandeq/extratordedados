"""
Tests for niche request endpoints (Phase 5).
Wave 0: all stubs skipped. Activate after Plan 02 backend is implemented.
"""
import pytest
import requests

API_BASE = "https://api.extratordedados.com.br"


@pytest.mark.skip(reason="Wave 0 stub — activate after Plan 02 backend")
def test_niche_request_created(api_base, client_token):
    """P5-NICHE-CREATE: POST creates a niche request or votes on existing."""
    import time
    unique_niche = f"Test Nicho {int(time.time())}"
    resp = requests.post(
        f"{api_base}/api/client/niche-requests",
        json={"niche": unique_niche, "city": "Vitória", "state": "ES"},
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=15,
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "niche_request_id" in data
    assert data.get("action") in ("created", "voted")


@pytest.mark.skip(reason="Wave 0 stub — activate after Plan 02 backend")
def test_niche_vote_dedup(api_base, client_token, auth_token):
    """P5-NICHE-VOTE: second request for same niche increments votes, no duplicate row."""
    import time
    unique_niche = f"Dedup Test {int(time.time())}"
    headers_client = {"Authorization": f"Bearer {client_token}"}
    # First request (creates)
    r1 = requests.post(
        f"{api_base}/api/client/niche-requests",
        json={"niche": unique_niche, "city": "Serra", "state": "ES"},
        headers=headers_client, timeout=15,
    )
    assert r1.status_code == 201
    req_id = r1.json()["niche_request_id"]
    votes_after_create = r1.json()["votes"]
    assert votes_after_create == 1

    # Second request from admin (different user — should vote, not create)
    r2 = requests.post(
        f"{api_base}/api/client/niche-requests",
        json={"niche": unique_niche, "city": "Serra", "state": "ES"},
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15,
    )
    # admin posting to client endpoint — 403 if require_role('client') blocks admin, or 200/201
    # If admin is blocked at role check, skip
    if r2.status_code == 403:
        pytest.skip("Admin cannot access client niche-requests endpoint — need second client user to test dedup")
    assert r2.status_code == 200  # voted, not created
    assert r2.json().get("action") == "voted"
    assert r2.json()["niche_request_id"] == req_id


@pytest.mark.skip(reason="Wave 0 stub — activate after Plan 02 backend")
def test_admin_niche_list(api_base, auth_headers):
    """P5-NICHE-ADMIN-LIST: admin can list all niche requests sorted by votes."""
    resp = requests.get(
        f"{api_base}/api/admin/niche-requests",
        headers=auth_headers, timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "requests" in data
    items = data["requests"]
    if len(items) > 1:
        # Verify sorted by votes desc
        votes_list = [r["votes"] for r in items]
        assert votes_list == sorted(votes_list, reverse=True)


@pytest.mark.skip(reason="Wave 0 stub — activate after Plan 02 backend")
def test_admin_approve_niche(api_base, client_token, auth_headers):
    """P5-NICHE-APPROVE: admin approve sets status to processing."""
    import time
    unique_niche = f"Approve Test {int(time.time())}"
    # Create a request first
    create_resp = requests.post(
        f"{api_base}/api/client/niche-requests",
        json={"niche": unique_niche, "city": "Vitória", "state": "ES"},
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=15,
    )
    if create_resp.status_code not in (200, 201):
        pytest.skip("Could not create niche request — check Plan 02 implementation")
    req_id = create_resp.json()["niche_request_id"]

    # Admin approves
    approve_resp = requests.post(
        f"{api_base}/api/admin/niche-requests/{req_id}/approve",
        headers=auth_headers, timeout=15,
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json().get("status") == "processing"
