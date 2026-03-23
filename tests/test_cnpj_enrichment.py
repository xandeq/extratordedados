"""
Smoke tests for CNPJ enrichment — Phase 3.
Run: python -m pytest tests/test_cnpj_enrichment.py -v
Requires: live API at https://api.extratordedados.com.br + ADMIN_PASSWORD in AWS SM extratordedados/prod
"""
import pytest
import requests


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 01 deploys")
def test_enrich_cnpj_endpoint_returns_200(api_base, auth_headers):
    """POST /api/leads/enrich-cnpj with valid CNPJ returns 200 and enrichment data."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 01 deploys")
def test_enrich_cnpj_fallback_chain_order(api_base, auth_headers):
    """Fallback chain tries rf_local first, then external providers."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 01 deploys")
def test_enrich_cnpj_invalid_returns_400(api_base, auth_headers):
    """POST /api/leads/enrich-cnpj with 13-digit CNPJ returns 400."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implement after Plan 01 deploys")
def test_enrich_cnpj_normalizes_response(api_base, auth_headers):
    """Response always contains razao_social, situacao, source keys."""
    pass
