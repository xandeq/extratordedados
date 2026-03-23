"""
Smoke tests + unit stubs — Phase 2 Lead Quality endpoints.
Live smoke tests run against: https://api.extratordedados.com.br
Unit tests (Wave 2): test the quality functions directly via module import.
"""
import pytest
import requests


# ── Live smoke tests (run against deployed API) ────────────────────────────

def test_validate_email_free_endpoint_requires_auth(api_base):
    """POST /api/leads/validate-email-free without auth returns 401."""
    resp = requests.post(f"{api_base}/api/leads/validate-email-free",
                         json={"email": "test@mailinator.com"}, timeout=10)
    assert resp.status_code == 401


def test_normalize_phone_endpoint_requires_auth(api_base):
    """POST /api/leads/normalize-phone without auth returns 401."""
    resp = requests.post(f"{api_base}/api/leads/normalize-phone",
                         json={"phone": "27999998888"}, timeout=10)
    assert resp.status_code == 401


def test_db_columns_health_still_ok(api_base):
    """Health endpoint must still return 200 after DB migration."""
    resp = requests.get(f"{api_base}/api/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_leads_list_returns_200_authenticated(api_base, auth_headers):
    """GET /api/leads with auth returns 200 and has 'leads' key."""
    resp = requests.get(f"{api_base}/api/leads?limit=1", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    assert "leads" in resp.json()


def test_validate_batch_requires_auth(api_base):
    """POST /api/leads/validate-batch without auth returns 401."""
    resp = requests.post(f"{api_base}/api/leads/validate-batch",
                         json={"batch_id": 1}, timeout=10)
    assert resp.status_code == 401


def test_validate_batch_authenticated(api_base, auth_headers):
    """POST /api/leads/validate-batch with auth returns 200 or 400 (not 401/404 after Wave 2)."""
    # Use a non-existent batch_id (truthy) to avoid full-table scan timeout on admin users
    # batch_id=0 is falsy in Python — endpoint would scan all leads for admin users
    resp = requests.post(f"{api_base}/api/leads/validate-batch",
                         json={"batch_id": 999999999}, headers=auth_headers, timeout=10)
    # 200 = success (batch not found = 0 leads updated), 400 = validation error
    assert resp.status_code in (200, 400)


def test_verify_email_requires_auth(api_base):
    """POST /api/leads/1/verify-email without auth returns 401."""
    resp = requests.post(f"{api_base}/api/leads/1/verify-email",
                         json={}, timeout=10)
    assert resp.status_code == 401


def test_quality_grade_field_present_in_lead(api_base, auth_headers):
    """After DB migration, GET /api/leads response items include quality_grade field (may be null)."""
    resp = requests.get(f"{api_base}/api/leads?limit=1", headers=auth_headers, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    leads = body.get("leads", [])
    if leads:
        # quality_grade key must be present (value may be None until scoring runs)
        assert "quality_grade" in leads[0], "quality_grade field missing from lead response"


# ── Unit tests (Wave 2 — test quality functions directly) ─────────────────
# These tests import functions directly from app.py.
# If app.py cannot be imported (requires DB/Gunicorn), tests are skipped with ImportError guard.

def _import_quality_fns():
    """Lazy import of quality functions to avoid module-level import failure."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'backend'))
    import importlib
    try:
        m = importlib.import_module('app')
        return m.validate_email_free, m.normalize_phone_br, m.compute_lead_quality_score
    except Exception as e:
        raise ImportError(f"Cannot import app.py: {e}")


def test_validate_email_free_invalid_mx():
    """validate_email_free() rejects email with no MX record."""
    try:
        validate_email_free, _, _ = _import_quality_fns()
    except ImportError as e:
        pytest.skip(f"app.py not importable in test environment: {e}")
    result = validate_email_free('bad@nodomain12345invalid.com')
    assert result['valid'] is False
    assert 'no_mx_record' in (result.get('reason') or '')


def test_validate_email_free_disposable():
    """validate_email_free() rejects disposable domain (mailinator.com)."""
    try:
        validate_email_free, _, _ = _import_quality_fns()
    except ImportError as e:
        pytest.skip(f"app.py not importable in test environment: {e}")
    result = validate_email_free('test@mailinator.com')
    assert result['valid'] is False
    assert result.get('is_disposable') is True


def test_normalize_phone_br_mobile():
    """normalize_phone_br() correctly normalizes a Brazilian mobile number."""
    try:
        _, normalize_phone_br, _ = _import_quality_fns()
    except ImportError as e:
        pytest.skip(f"app.py not importable in test environment: {e}")
    result = normalize_phone_br('27999998888')
    assert result['valid'] is True
    assert result['e164'] == '+5527999998888'
    assert result['type'] == 'mobile'
    assert result['whatsapp_id'] == '5527999998888@c.us'


def test_normalize_phone_br_invalid():
    """normalize_phone_br() returns valid=False for invalid input."""
    try:
        _, normalize_phone_br, _ = _import_quality_fns()
    except ImportError as e:
        pytest.skip(f"app.py not importable in test environment: {e}")
    result = normalize_phone_br('27XXXX')
    assert result['valid'] is False


def test_quality_score_complete_lead():
    """compute_lead_quality_score() scores a complete lead as grade B or A (score >= 60)."""
    try:
        _, _, compute_lead_quality_score = _import_quality_fns()
    except ImportError as e:
        pytest.skip(f"app.py not importable in test environment: {e}")
    lead = {
        'email': 'contato@empresa.com.br',
        'phone': '27999998888',
        'company_name': 'Empresa Teste',
        'city': 'Vitória',
        'state': 'ES',
        'source': 'google_maps',
    }
    result = compute_lead_quality_score(lead)
    assert result['score'] >= 60
    assert result['grade'] in ('A', 'B')


def test_quality_score_no_email():
    """compute_lead_quality_score() scores a lead with no email/phone as grade D or F (score <= 20)."""
    try:
        _, _, compute_lead_quality_score = _import_quality_fns()
    except ImportError as e:
        pytest.skip(f"app.py not importable in test environment: {e}")
    result = compute_lead_quality_score({'email': None, 'phone': None})
    assert result['score'] <= 20
    assert result['grade'] in ('D', 'F')
