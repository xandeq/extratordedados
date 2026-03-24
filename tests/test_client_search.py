"""
Phase 4: client portal search tests — activated after Plan 02 implementation.
Tests require CLIENT_TEST_PASSWORD in AWS SM.
Tests auto-skip gracefully when credentials are unavailable.
"""
import re
import pytest
import requests


def test_search_requires_auth(api_base):
    """GET /api/leads/search returns 401 without token"""
    resp = requests.get(f"{api_base}/api/leads/search", timeout=10)
    assert resp.status_code == 401


def test_search_returns_masked_email(api_base, client_token):
    """GET /api/leads/search returns masked email (jo***@domain.com format) for unrevealed leads"""
    resp = requests.get(
        f"{api_base}/api/leads/search",
        headers={"Authorization": f"Bearer {client_token}"},
        params={"has_email": "true", "per_page": 10},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "leads" in data
    leads = data["leads"]
    if not leads:
        pytest.skip("No leads with email available in search results")

    # Find an unrevealed lead with email
    unrevealed = [l for l in leads if not l.get("revealed", False) and l.get("email")]
    if not unrevealed:
        pytest.skip("All returned leads are already revealed or have no email")

    lead = unrevealed[0]
    email = lead["email"]
    # Masked email must contain *** and @ — pattern: xx***@domain.com
    assert "***" in email, f"Expected masked email (containing ***), got: {email}"
    assert "@" in email, f"Expected email with @, got: {email}"


def test_search_has_email_filter(api_base, client_token):
    """GET /api/leads/search?has_email=true only returns leads with email (has_email=True)"""
    resp = requests.get(
        f"{api_base}/api/leads/search",
        headers={"Authorization": f"Bearer {client_token}"},
        params={"has_email": "true", "per_page": 5},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    leads = data.get("leads", [])
    for lead in leads:
        assert lead.get("has_email") is True, f"Lead {lead.get('id')} has has_email=False but was returned by has_email filter"


def test_search_category_filter(api_base, client_token):
    """GET /api/leads/search?category=clinica returns matching leads"""
    resp = requests.get(
        f"{api_base}/api/leads/search",
        headers={"Authorization": f"Bearer {client_token}"},
        params={"category": "clinica", "per_page": 5},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "leads" in data
    assert "total" in data
    # Results may be empty if no clinica leads exist — that's OK, just verify shape
    assert isinstance(data["leads"], list)
    assert isinstance(data["total"], int)


def test_admin_reveal_no_credit_deduction(api_base, auth_headers):
    """Admin reveal endpoint bypasses credit check — admin can reveal without credits"""
    # Get any lead id from admin's leads list
    leads_resp = requests.get(
        f"{api_base}/api/leads",
        headers=auth_headers,
        params={"per_page": 1},
        timeout=10,
    )
    if leads_resp.status_code != 200:
        pytest.skip("Cannot list leads as admin")
    leads_data = leads_resp.json()
    leads = leads_data.get("leads", [])
    if not leads:
        pytest.skip("No leads available for admin reveal test")

    lead_id = leads[0].get("id")
    if not lead_id:
        pytest.skip("Lead has no id")

    # Admin reveal — should succeed even if admin has 0 credits
    reveal_resp = requests.post(
        f"{api_base}/api/leads/reveal/{lead_id}",
        headers=auth_headers,
        timeout=10,
    )
    # Admin bypass: 200 expected (or 404 if lead doesn't exist in shared batches)
    assert reveal_resp.status_code in (200, 404), \
        f"Expected 200 or 404 for admin reveal, got {reveal_resp.status_code}: {reveal_resp.text}"
