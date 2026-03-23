"""
Smoke tests + unit stubs — Phase 2 Lead Quality endpoints.
Live smoke tests run against: https://api.extratordedados.com.br
Unit stubs (marked skip) require Wave 2 implementation before unskipping.
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
    resp = requests.post(f"{api_base}/api/leads/validate-batch",
                         json={}, headers=auth_headers, timeout=10)
    # Before Wave 2: 404 expected. After Wave 2: 200 or 400 (bad request without batch_id).
    assert resp.status_code in (200, 400, 404)


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


# ── Unit stubs (skipped until Wave 2 implements the functions) ─────────────
# Function names MUST match VALIDATION.md exactly — do not rename.
# In Wave 2 (Plan 02 Task 1): remove the @pytest.mark.skip decorators and
# add `from app.backend.app import validate_email_free, normalize_phone_br, compute_lead_quality_score`
# at the top of this section.

@pytest.mark.skip(reason="Wave 0 stub — validate_email_free() not yet implemented (Wave 2)")
def test_validate_email_free_invalid_mx():
    """validate_email_free() rejects email with no MX record."""
    # from app.backend.app import validate_email_free  # uncomment in Wave 2
    result = validate_email_free('bad@nodomain12345invalid.com')  # noqa: F821
    assert result['valid'] is False
    assert 'no_mx_record' in (result.get('reason') or '')


@pytest.mark.skip(reason="Wave 0 stub — validate_email_free() not yet implemented (Wave 2)")
def test_validate_email_free_disposable():
    """validate_email_free() rejects disposable domain (mailinator.com)."""
    # from app.backend.app import validate_email_free  # uncomment in Wave 2
    result = validate_email_free('test@mailinator.com')  # noqa: F821
    assert result['valid'] is False
    assert result.get('is_disposable') is True


@pytest.mark.skip(reason="Wave 0 stub — normalize_phone_br() not yet implemented (Wave 2)")
def test_normalize_phone_br_mobile():
    """normalize_phone_br() correctly normalizes a Brazilian mobile number."""
    # from app.backend.app import normalize_phone_br  # uncomment in Wave 2
    result = normalize_phone_br('27999998888')  # noqa: F821
    assert result['valid'] is True
    assert result['e164'] == '+5527999998888'
    assert result['type'] == 'mobile'
    assert result['whatsapp_id'] == '5527999998888@c.us'


@pytest.mark.skip(reason="Wave 0 stub — normalize_phone_br() not yet implemented (Wave 2)")
def test_normalize_phone_br_invalid():
    """normalize_phone_br() returns valid=False for invalid input."""
    # from app.backend.app import normalize_phone_br  # uncomment in Wave 2
    result = normalize_phone_br('27XXXX')  # noqa: F821
    assert result['valid'] is False


@pytest.mark.skip(reason="Wave 0 stub — compute_lead_quality_score() not yet implemented (Wave 2)")
def test_quality_score_complete_lead():
    """compute_lead_quality_score() scores a complete lead as grade B or A (score >= 60)."""
    # from app.backend.app import compute_lead_quality_score  # uncomment in Wave 2
    lead = {
        'email': 'contato@empresa.com.br',
        'phone': '27999998888',
        'company_name': 'Empresa Teste',
        'city': 'Vitória',
        'state': 'ES',
        'source': 'google_maps',
    }
    result = compute_lead_quality_score(lead)  # noqa: F821
    assert result['score'] >= 60
    assert result['grade'] in ('A', 'B')


@pytest.mark.skip(reason="Wave 0 stub — compute_lead_quality_score() not yet implemented (Wave 2)")
def test_quality_score_no_email():
    """compute_lead_quality_score() scores a lead with no email/phone as grade D or F (score <= 20)."""
    # from app.backend.app import compute_lead_quality_score  # uncomment in Wave 2
    result = compute_lead_quality_score({'email': None, 'phone': None})  # noqa: F821
    assert result['score'] <= 20
    assert result['grade'] in ('D', 'F')
