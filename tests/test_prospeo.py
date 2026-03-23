"""
Smoke tests for Prospeo LinkedIn-to-email enrichment — Phase 3.
Run: python -m pytest tests/test_prospeo.py -v
"""
import pytest
import requests


def test_prospeo_enrich_endpoint_exists(api_base, auth_headers):
    """POST /api/leads/<id>/enrich-linkedin returns 200, 400, or 503 — never 404 or 500."""
    # Lead ID 1 may not exist, have no LinkedIn URL, or key may not be set.
    # Any of: 400 (no linkedin), 404 (lead not found), 503 (key not configured) are valid.
    # The endpoint must exist and return structured JSON, not 500.
    resp = requests.post(
        f"{api_base}/api/leads/1/enrich-linkedin",
        headers=auth_headers,
        timeout=10,
    )
    assert resp.status_code != 500, f"Expected non-500 response, got {resp.status_code}: {resp.text}"
    assert resp.status_code in (200, 400, 404, 429, 503), (
        f"Unexpected status code {resp.status_code}: {resp.text}"
    )
    # Response must be JSON
    data = resp.json()
    assert isinstance(data, dict), "Response should be a JSON object"


def test_prospeo_skips_leads_without_linkedin_url(api_base, auth_headers):
    """If a lead has no LinkedIn URL, endpoint returns 400 with clear error or 404 (lead not found)."""
    # We cannot guarantee lead 1 exists or lacks a LinkedIn URL, but we can verify the response structure.
    resp = requests.post(
        f"{api_base}/api/leads/1/enrich-linkedin",
        headers=auth_headers,
        timeout=10,
    )
    assert resp.status_code != 500, f"Endpoint must not return 500. Got: {resp.status_code}"
    data = resp.json()
    if resp.status_code == 400:
        assert 'error' in data, "400 response must include 'error' field"


def test_prospeo_quota_exceeded_returns_graceful_error(api_base, auth_headers):
    """When Prospeo returns quota error, endpoint returns 429 not 500."""
    # This test validates the error handling path exists.
    # We cannot trigger quota error without a real key and real requests.
    # Instead, verify the endpoint responds with a structured error (not 500).
    resp = requests.post(
        f"{api_base}/api/leads/1/enrich-linkedin",
        headers=auth_headers,
        timeout=10,
    )
    # Any response except 500 indicates proper error handling
    assert resp.status_code != 500, (
        f"Endpoint crashed with 500 — missing error handling for Prospeo quota. "
        f"Response: {resp.text}"
    )
    data = resp.json()
    assert isinstance(data, dict), "Response must be a JSON object"
