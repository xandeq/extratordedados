"""
Wave 0 stubs — Phase 4: client portal search tests.
All tests are skipped pending implementation (Wave 1+).
"""
import pytest


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_search_requires_auth(api_base):
    """GET /api/leads/search returns 401 without token"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_search_returns_masked_email(api_base, client_token):
    """GET /api/leads/search returns masked email (jo***@gmail.com format)"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_search_has_email_filter(api_base, client_token):
    """GET /api/leads/search?has_email=true only returns leads with email"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_search_category_filter(api_base, client_token):
    """GET /api/leads/search?category=clinica returns matching leads"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_admin_reveal_no_credit_deduction(api_base, auth_headers):
    """Admin reveal endpoint bypasses credit check"""
    pass
