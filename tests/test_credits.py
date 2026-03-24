"""
Wave 0 stubs — Phase 4: credit ledger tests.
All tests are skipped pending implementation (Wave 1+).
"""
import pytest

API_BASE = "https://api.extratordedados.com.br"


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_credits_requires_auth(api_base):
    """GET /api/client/credits returns 401 without token"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_credits_returns_balance(api_base, client_token):
    """GET /api/client/credits returns balance and history for authed client"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_monthly_grant_inserts_ledger(api_base, auth_headers):
    """grant_monthly_credits() inserts a row in credit_ledger"""
    pass
