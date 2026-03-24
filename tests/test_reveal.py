"""
Wave 0 stubs — Phase 4: reveal gate tests.
All tests are skipped pending implementation (Wave 1+).
"""
import pytest


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_reveal_requires_auth(api_base):
    """POST /api/leads/reveal/<id> returns 401 without token"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_reveal_insufficient_credits(api_base, client_token):
    """POST /api/leads/reveal/<id> returns 402 when balance=0"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_reveal_success_deducts_credit(api_base, client_token):
    """POST /api/leads/reveal/<id> deducts 1 credit and returns email"""
    pass


@pytest.mark.skip(reason="Wave 0 — implementation pending")
def test_reveal_idempotent(api_base, client_token):
    """Re-revealing same lead does NOT deduct second credit"""
    pass
