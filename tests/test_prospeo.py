"""
Smoke tests for Prospeo LinkedIn-to-email enrichment — Phase 3.
Run: python -m pytest tests/test_prospeo.py -v
"""
import pytest


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 03 deploys")
def test_prospeo_enrich_endpoint_exists(api_base, auth_headers):
    """POST /api/leads/<id>/enrich-linkedin returns 200 or 404 (not 500)."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 03 deploys")
def test_prospeo_skips_leads_without_linkedin_url(api_base, auth_headers):
    """Lead with empty linkedin field returns 400 with clear error message."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 03 deploys")
def test_prospeo_quota_exceeded_returns_graceful_error(api_base, auth_headers):
    """When Prospeo returns 402/quota error, endpoint returns 429 not 500."""
    pass
