"""
Smoke tests for Outscraper massive search method — Phase 3.
Run: python -m pytest tests/test_outscraper.py -v
"""
import pytest


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 02 deploys")
def test_massive_search_accepts_outscraper_method(api_base, auth_headers):
    """POST /api/search/massive with methods=['outscraper_maps'] starts a batch."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 02 deploys")
def test_massive_search_response_includes_outscraper_count(api_base, auth_headers):
    """Response JSON contains outscraper_maps key in jobs breakdown."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 02 deploys")
def test_outscraper_quota_exceeded_does_not_crash(api_base, auth_headers):
    """When outscraper returns 429, job marked failed/quota_exceeded, batch continues."""
    pass
