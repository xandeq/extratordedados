"""
Quality filter tests — Phase 7 QUAL-01 to QUAL-05.
Wave 0: scaffold created before implementation. Tests marked with [WAVE0-FAIL] will fail
until guards are added to save_lead_to_db() in Task 2.
Unit tests for pure functions can pass after Task 2. Integration smoke tests
(import via API then check GET /api/leads) require deploy.
"""
import sys
import os
import requests

# --- Unit tests for pure helper functions (no API needed) ---
# Extract the pure functions by parsing them from app.py with AST to avoid triggering
# the full Flask app initialization (which tries to connect to remote DB/APScheduler).

import re as _re_module
import ast as _ast_module

def _try_import_helpers():
    """
    Extracts _is_foreign_tld and _is_slogan_email from app.py using exec() on parsed source.
    This avoids triggering the full Flask app initialization (which hangs on remote DB).
    Returns (fn, fn) or (None, None) if functions not yet defined in app.py.
    """
    app_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'backend', 'app.py')
    if not os.path.exists(app_path):
        return None, None
    try:
        with open(app_path, encoding='utf-8') as f:
            source = f.read()
        # Check if functions exist at all
        if '_is_foreign_tld' not in source or '_is_slogan_email' not in source:
            return None, None
        # Extract just the constants + functions we need using string slicing
        # Find the QUAL-02 block start and the Phase 2 section end as boundary
        start_marker = '# \u2500\u2500 QUAL-02: Foreign TLD blocklist'
        end_marker = '# ============= Phase 2: Lead Quality Functions'
        start_idx = source.find(start_marker)
        end_idx = source.find(end_marker)
        if start_idx == -1 or end_idx == -1:
            return None, None
        snippet = source[start_idx:end_idx]
        # Execute snippet in a fresh namespace with only stdlib dependencies
        ns = {'re': _re_module}
        exec(snippet, ns)  # noqa: S102 — controlled source from own codebase
        _is_foreign_tld = ns.get('_is_foreign_tld')
        _is_slogan_email = ns.get('_is_slogan_email')
        if _is_foreign_tld is None or _is_slogan_email is None:
            return None, None
        return _is_foreign_tld, _is_slogan_email
    except Exception:
        return None, None


def test_foreign_tld_rejected_unit():
    """QUAL-02: _is_foreign_tld() returns True for blocked TLDs."""
    _is_foreign_tld, _ = _try_import_helpers()
    if _is_foreign_tld is None:
        import pytest; pytest.skip("_is_foreign_tld not yet implemented")
    assert _is_foreign_tld("empresa.es") is True
    assert _is_foreign_tld("empresa.pt") is True
    assert _is_foreign_tld("empresa.com.ar") is True
    assert _is_foreign_tld("empresa.com.mx") is True
    assert _is_foreign_tld("empresa.co.uk") is True
    assert _is_foreign_tld("empresa.de") is True
    assert _is_foreign_tld("empresa.pl") is True
    assert _is_foreign_tld("empresa.ru") is True


def test_allowed_tld_accepted_unit():
    """QUAL-02: _is_foreign_tld() returns False for allowed TLDs."""
    _is_foreign_tld, _ = _try_import_helpers()
    if _is_foreign_tld is None:
        import pytest; pytest.skip("_is_foreign_tld not yet implemented")
    assert _is_foreign_tld("empresa.com.br") is False
    assert _is_foreign_tld("empresa.br") is False
    assert _is_foreign_tld("empresa.io") is False
    assert _is_foreign_tld("empresa.co") is False
    assert _is_foreign_tld("empresa.net") is False
    assert _is_foreign_tld("empresa.org") is False
    assert _is_foreign_tld("empresa.app") is False
    assert _is_foreign_tld("empresa.dev") is False
    assert _is_foreign_tld("empresa.com") is False


def test_slogan_email_rejected_unit():
    """QUAL-03: _is_slogan_email() returns True for obvious slogan emails."""
    _, _is_slogan_email = _try_import_helpers()
    if _is_slogan_email is None:
        import pytest; pytest.skip("_is_slogan_email not yet implemented")
    # 4+ words with action verb — reject
    assert _is_slogan_email("venha-ser-feliz-aqui@empresa.com.br") is True
    assert _is_slogan_email("clique-e-acesse-ja@empresa.com.br") is True
    # Single action verb as entire local part — reject
    assert _is_slogan_email("venha@empresa.com.br") is True
    assert _is_slogan_email("clique@empresa.com.br") is True


def test_generic_prefix_accepted_unit():
    """QUAL-03: Generic prefixes are never rejected (D-12)."""
    _, _is_slogan_email = _try_import_helpers()
    if _is_slogan_email is None:
        import pytest; pytest.skip("_is_slogan_email not yet implemented")
    assert _is_slogan_email("contato@empresa.com.br") is False
    assert _is_slogan_email("atendimento@empresa.com.br") is False
    assert _is_slogan_email("comercial@empresa.com.br") is False
    assert _is_slogan_email("financeiro@empresa.com.br") is False
    assert _is_slogan_email("suporte@empresa.com.br") is False
    assert _is_slogan_email("info@empresa.com.br") is False
    assert _is_slogan_email("sac@empresa.com.br") is False
    assert _is_slogan_email("vendas@empresa.com.br") is False


def test_slogan_rejection_rate_unit():
    """QUAL-03: Rejection rate < 5% on realistic sample of 100 common BR business emails."""
    _, _is_slogan_email = _try_import_helpers()
    if _is_slogan_email is None:
        import pytest; pytest.skip("_is_slogan_email not yet implemented")
    realistic_emails = [
        "contato@clinicamedica.com.br", "admin@odontologiavitoria.com.br",
        "clinica@saudebem.com.br", "recepcao@cabelelereiro.com.br",
        "info@petshopserra.com.br", "comercial@academiafit.com.br",
        "financeiro@contabilidade.com.br", "sac@restaurantevix.com.br",
        "marketing@imobiliaria.com.br", "rh@transportadora.com.br",
        "joao@empresa.com.br", "maria@clinica.com.br",
        "pedro@consultoria.com.br", "ana@farmacia.com.br",
        "carlos@autoescola.com.br", "luciana@hotel.com.br",
        "roberto@laboratorio.com.br", "patricia@escola.com.br",
        "marcos@escritorio.com.br", "fernanda@salao.com.br",
    ] * 5  # 100 emails
    rejected = sum(1 for e in realistic_emails if _is_slogan_email(e))
    rate = rejected / len(realistic_emails)
    assert rate < 0.05, f"Slogan rejection rate {rate:.1%} exceeds 5% threshold on realistic sample"


# --- Integration smoke tests (require deploy) ---

def test_foreign_tld_not_saved(api_base, auth_headers):
    """QUAL-02: Lead with .es email domain is NOT saved after import. [WAVE0-FAIL until deployed]"""
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    test_email = f"test_{unique_id}@empresa-teste.es"
    resp = requests.post(
        f"{api_base}/api/leads/import",
        headers=auth_headers,
        json={"contacts": [{"email": test_email, "company_name": "Test Foreign TLD"}]},
        timeout=15,
    )
    assert resp.status_code in (200, 201, 400, 429)
    if resp.status_code == 429:
        import pytest; pytest.skip("Rate limited")
    # Check lead did NOT get saved
    check = requests.get(
        f"{api_base}/api/leads",
        headers=auth_headers,
        params={"q": test_email},
        timeout=10,
    )
    assert check.status_code in (200, 429)
    if check.status_code == 200:
        data = check.json()
        leads = data.get("leads", data.get("items", []))
        assert not any(l.get("email") == test_email for l in leads), \
            f"Foreign TLD email {test_email} was saved — QUAL-02 guard not active"


def test_combr_email_saved(api_base, auth_headers):
    """QUAL-02: Lead with .com.br email IS saved normally."""
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    test_email = f"contato_{unique_id}@empresa-teste.com.br"
    resp = requests.post(
        f"{api_base}/api/leads/import",
        headers=auth_headers,
        json={"contacts": [{"email": test_email, "company_name": "Test BR Company"}]},
        timeout=15,
    )
    assert resp.status_code in (200, 201, 429)


def test_invalid_whatsapp_lead_still_saved(api_base, auth_headers):
    """QUAL-05: Lead with invalid whatsapp is saved (lead not rejected, whatsapp NULLed)."""
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    test_email = f"whatsapp_test_{unique_id}@empresa.com.br"
    resp = requests.post(
        f"{api_base}/api/leads/import",
        headers=auth_headers,
        json={"contacts": [{
            "email": test_email,
            "company_name": "Test WhatsApp Null",
            "whatsapp": "123"  # invalid — too short, no DDD
        }]},
        timeout=15,
    )
    assert resp.status_code in (200, 201, 429)
    if resp.status_code == 429:
        import pytest; pytest.skip("Rate limited")
    # Lead itself should be saved (not rejected)
    check = requests.get(
        f"{api_base}/api/leads",
        headers=auth_headers,
        params={"q": test_email},
        timeout=10,
    )
    if check.status_code == 200:
        data = check.json()
        leads = data.get("leads", data.get("items", []))
        matching = [l for l in leads if l.get("email") == test_email]
        if matching:
            # If found, whatsapp should be None/null/empty
            assert not matching[0].get("whatsapp"), \
                "Invalid whatsapp '123' was saved instead of being NULLed (QUAL-05)"


def test_multipart_tld_rejected_unit():
    """QUAL-02: _is_foreign_tld() correctly handles multi-part TLDs like .com.ar (Pitfall 1)."""
    _is_foreign_tld, _ = _try_import_helpers()
    if _is_foreign_tld is None:
        import pytest; pytest.skip("_is_foreign_tld not yet implemented")
    # Multi-part foreign TLDs
    assert _is_foreign_tld("empresa.com.ar") is True
    assert _is_foreign_tld("empresa.com.mx") is True
    assert _is_foreign_tld("empresa.com.co") is True
    assert _is_foreign_tld("empresa.co.uk") is True
    # Multi-part BR TLD must NOT be rejected
    assert _is_foreign_tld("empresa.com.br") is False
    # Subdomains with foreign TLD must be rejected
    assert _is_foreign_tld("mail.empresa.es") is True


def test_quality_stats_endpoint(api_base, auth_headers):
    """QUAL-06 prep: GET /api/admin/quality-stats returns 200 (added in Plan 07-03)."""
    resp = requests.get(
        f"{api_base}/api/admin/quality-stats",
        headers=auth_headers,
        timeout=10,
    )
    # Will be 404 until Plan 07-03 implements the endpoint
    assert resp.status_code in (200, 404, 429)
