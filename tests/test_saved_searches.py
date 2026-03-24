"""Phase 6: Saved Searches + Notifications — smoke tests."""
import pytest
import requests


# ── Auth guard ─────────────────────────────────────────────────────────────
def test_saved_search_auth(api_base):
    """POST without token must return 401."""
    resp = requests.post(f"{api_base}/api/client/saved-searches", json={}, timeout=10)
    assert resp.status_code == 401


# ── CRUD stubs (activate in Plan 02) ───────────────────────────────────────
def test_saved_search_created(api_base, client_token):
    pytest.skip("not implemented yet — Wave 1")


def test_saved_search_list(api_base, client_token):
    pytest.skip("not implemented yet — Wave 1")


def test_saved_search_delete(api_base, client_token):
    pytest.skip("not implemented yet — Wave 1")


def test_saved_search_toggle(api_base, client_token):
    pytest.skip("not implemented yet — Wave 1")


# ── Email helper unit test ──────────────────────────────────────────────────
def test_notification_email_format():
    pytest.skip("not implemented yet — Wave 1")
