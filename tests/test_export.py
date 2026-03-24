"""
Tests for GET /api/client/leads/export (Phase 5).
Wave 0: all stubs skipped. Activate stubs after Plan 01 backend is implemented.
"""
import pytest
import requests

API_BASE = "https://api.extratordedados.com.br"


def test_export_requires_auth(api_base):
    """P5-EXPORT-AUTH: export endpoint returns 401 without token."""
    resp = requests.get(f"{api_base}/api/client/leads/export", timeout=10)
    if resp.status_code == 404:
        pytest.skip("Endpoint not yet deployed to VPS — deploy Plan 01 backend first")
    assert resp.status_code == 401


def test_export_csv_format(api_base, client_token):
    """P5-EXPORT-FORMAT: export returns text/csv Content-Type when format=csv."""
    resp = requests.get(
        f"{api_base}/api/client/leads/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=30,
    )
    # 200 or 404 (no leads) — either way, if 200, must be text/csv
    if resp.status_code == 200:
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "attachment" in resp.headers.get("Content-Disposition", "")
    else:
        assert resp.status_code in (402, 404)


def test_export_debits_credits(api_base, client_token):
    """P5-EXPORT-CREDITS: export deducts credits equal to leads exported."""
    import json
    # Get balance before
    before = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    ).json()
    balance_before = before.get("balance", 0)
    if balance_before == 0:
        pytest.skip("No credits available for test_client — seed credits first")

    # Do export
    resp = requests.get(
        f"{api_base}/api/client/leads/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=30,
    )
    if resp.status_code == 404:
        pytest.skip("No shared leads in DB to export")
    assert resp.status_code == 200

    # Count exported rows (subtract 1 for header)
    lines = resp.content.decode("utf-8-sig").strip().split("\n")
    exported_count = max(0, len(lines) - 1)

    # Get balance after
    after = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    ).json()
    balance_after = after.get("balance", 0)
    assert balance_before - balance_after == exported_count


def test_export_respects_cap(api_base, client_token):
    """P5-EXPORT-CAP: export never returns more rows than current balance."""
    before = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    ).json()
    balance = before.get("balance", 0)

    resp = requests.get(
        f"{api_base}/api/client/leads/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=30,
    )
    if resp.status_code in (402, 404):
        pytest.skip("No credits or no leads")
    assert resp.status_code == 200
    lines = resp.content.decode("utf-8-sig").strip().split("\n")
    exported_count = max(0, len(lines) - 1)
    assert exported_count <= balance
