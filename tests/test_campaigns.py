"""Smoke tests for Email Campaigns module (/api/campaigns/*)."""
import pytest
import requests


BASE = "https://api.extratordedados.com.br"


@pytest.fixture(scope="module")
def auth(auth_headers):
    """Re-export session-scoped auth_headers for module-scoped fixtures below."""
    return auth_headers


# ─── Auth boundary ─────────────────────────────────────────────────────────

def test_list_campaigns_no_auth():
    r = requests.get(f"{BASE}/api/campaigns", timeout=10)
    assert r.status_code == 401


def test_create_campaign_no_auth():
    r = requests.post(f"{BASE}/api/campaigns", json={"name": "x"}, timeout=10)
    assert r.status_code == 401


def test_provider_status_no_auth():
    r = requests.get(f"{BASE}/api/campaigns/provider-status", timeout=10)
    assert r.status_code == 401


# ─── Provider status ───────────────────────────────────────────────────────

def test_provider_status_returns_four_providers(auth):
    r = requests.get(f"{BASE}/api/campaigns/provider-status", headers=auth, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 4
    names = {p["provider"] for p in data}
    assert names == {"brevo", "mailjet", "sendpulse", "resend"}
    for p in data:
        assert "used" in p and "limit" in p and "remaining" in p
        assert p["remaining"] == p["limit"] - p["used"]


# ─── Campaign CRUD ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def campaign_id(auth):
    """Create a campaign and return its id; delete after tests."""
    r = requests.post(f"{BASE}/api/campaigns", headers=auth, json={
        "name": "smoke-test-campaign",
        "steps": [
            {"step_num": 1, "subject": "Oi", "body_html": "<p>Teste</p>", "delay_days": 0, "condition": "always"},
        ],
        "target_filter": {"limit": 1},
    }, timeout=10)
    assert r.status_code == 201
    cid = r.json()["id"]
    yield cid
    # cleanup
    requests.delete(f"{BASE}/api/campaigns/{cid}", headers=auth, timeout=10)


def test_list_returns_created_campaign(auth, campaign_id):
    r = requests.get(f"{BASE}/api/campaigns", headers=auth, timeout=10)
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert campaign_id in ids


def test_get_campaign_detail(auth, campaign_id):
    r = requests.get(f"{BASE}/api/campaigns/{campaign_id}", headers=auth, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "smoke-test-campaign"
    assert len(data["steps"]) == 1
    assert data["status"] == "draft"


def test_get_nonexistent_campaign_returns_404(auth):
    r = requests.get(f"{BASE}/api/campaigns/999999", headers=auth, timeout=10)
    assert r.status_code == 404


def test_campaign_stats(auth, campaign_id):
    r = requests.get(f"{BASE}/api/campaigns/{campaign_id}/stats", headers=auth, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "total" in data and "sent" in data and "open_rate" in data


def test_update_campaign_name(auth, campaign_id):
    r = requests.put(f"{BASE}/api/campaigns/{campaign_id}", headers=auth, json={
        "name": "smoke-test-renamed"
    }, timeout=10)
    assert r.status_code == 200
    assert r.json().get("updated") is True
    # verify rename persisted
    r2 = requests.get(f"{BASE}/api/campaigns/{campaign_id}", headers=auth, timeout=10)
    assert r2.json()["name"] == "smoke-test-renamed"


def test_send_campaign_returns_202(auth, campaign_id):
    r = requests.post(f"{BASE}/api/campaigns/{campaign_id}/send", headers=auth, timeout=15)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "queued"
    assert "leads_to_process" in data


def test_send_already_sending_returns_409(auth, campaign_id):
    """Campaign is now 'sending' or 'active' — re-send should 409."""
    import time; time.sleep(1)
    r = requests.get(f"{BASE}/api/campaigns/{campaign_id}", headers=auth, timeout=10)
    status = r.json().get("status", "")
    if status == "sending":
        r2 = requests.post(f"{BASE}/api/campaigns/{campaign_id}/send", headers=auth, timeout=10)
        assert r2.status_code == 409
    else:
        pytest.skip(f"Campaign status={status}, not 'sending' — skip double-send test")


# ─── Tracking endpoints (no auth, public) ─────────────────────────────────

def test_track_open_pixel_returns_gif():
    r = requests.get(f"{BASE}/api/track/o/nonexistent_token.png", timeout=10)
    assert r.status_code == 200
    assert r.headers.get("Content-Type") == "image/gif"
    assert len(r.content) > 0


def test_track_click_redirects():
    import urllib.parse
    target = urllib.parse.quote("https://extratordedados.com.br", safe="")
    r = requests.get(f"{BASE}/api/track/c/nonexistent?url={target}", allow_redirects=False, timeout=10)
    assert r.status_code in (301, 302)
    assert "extratordedados.com.br" in r.headers.get("Location", "")


def test_track_click_rejects_open_redirect():
    r = requests.get(f"{BASE}/api/track/c/nonexistent?url=javascript:alert(1)", allow_redirects=False, timeout=10)
    assert r.status_code in (301, 302)
    loc = r.headers.get("Location", "")
    assert "javascript:" not in loc


def test_track_unsubscribe_returns_html():
    r = requests.get(f"{BASE}/api/track/unsubscribe/nonexistent_token", timeout=10)
    assert r.status_code == 200
    assert "Descadastrado" in r.text


# ─── Image generation ─────────────────────────────────────────────────────

def test_image_health_returns_providers(auth):
    r = requests.get(f"{BASE}/api/images/health", headers=auth, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "overall" in data and "providers" in data
    assert "fal" in data["providers"]
    assert "openrouter" in data["providers"]


def test_image_models_returns_list(auth):
    r = requests.get(f"{BASE}/api/images/models", headers=auth, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    assert len(data["models"]) > 0


# ─── Campaign log endpoint ─────────────────────────────────────────────────

def test_campaign_log_no_auth(campaign_id):
    r = requests.get(f"{BASE}/api/campaigns/{campaign_id}/log", timeout=10)
    assert r.status_code == 401


def test_campaign_log_returns_paginated_data(auth, campaign_id):
    r = requests.get(f"{BASE}/api/campaigns/{campaign_id}/log", headers=auth, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert "pages" in data
    assert "items" in data
    assert isinstance(data["items"], list)


def test_campaign_log_item_fields(auth, campaign_id):
    r = requests.get(f"{BASE}/api/campaigns/{campaign_id}/log", headers=auth, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    if items:
        item = items[0]
        for field in ("id", "email", "provider", "status", "sent_at"):
            assert field in item, f"Missing field: {field}"


def test_campaign_log_status_filter(auth, campaign_id):
    r = requests.get(f"{BASE}/api/campaigns/{campaign_id}/log?status=sent", headers=auth, timeout=10)
    assert r.status_code == 200
    data = r.json()
    for item in data["items"]:
        assert item["status"] == "sent"


def test_campaign_log_nonexistent_returns_404(auth):
    r = requests.get(f"{BASE}/api/campaigns/999999/log", headers=auth, timeout=10)
    assert r.status_code == 404


# ─── Bounce webhooks ─────────────────────────────────────────────────────────

def test_brevo_webhook_unknown_event_is_ignored():
    r = requests.post(f"{BASE}/api/webhooks/bounces/brevo",
                      json={"event": "delivered", "email": "test@test.com"}, timeout=10)
    assert r.status_code == 200
    assert r.json().get("skipped") is True


def test_brevo_webhook_hard_bounce_accepted():
    r = requests.post(f"{BASE}/api/webhooks/bounces/brevo",
                      json={"event": "hard_bounce", "email": "nonexistent_bounce_test@example.com"}, timeout=10)
    assert r.status_code == 200
    assert "updated" in r.json()


def test_resend_webhook_unknown_event_is_ignored():
    r = requests.post(f"{BASE}/api/webhooks/bounces/resend",
                      json={"type": "email.sent", "data": {"to": ["test@test.com"]}}, timeout=10)
    assert r.status_code == 200
    assert r.json().get("skipped") is True


def test_resend_webhook_bounce_accepted():
    r = requests.post(f"{BASE}/api/webhooks/bounces/resend",
                      json={"type": "email.bounced",
                            "data": {"to": ["nonexistent_bounce_test@example.com"]}}, timeout=10)
    assert r.status_code == 200
    assert "updated" in r.json()


def test_resend_webhook_missing_email_returns_400():
    r = requests.post(f"{BASE}/api/webhooks/bounces/resend",
                      json={"type": "email.bounced", "data": {}}, timeout=10)
    assert r.status_code == 400
