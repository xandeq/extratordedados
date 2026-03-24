"""
Phase 4: reveal gate tests — activated after Plan 02 implementation.
Tests require CLIENT_TEST_PASSWORD in AWS SM.
Tests auto-skip gracefully when credentials are unavailable.
"""
import pytest
import requests


def test_reveal_requires_auth(api_base):
    """POST /api/leads/reveal/<id> returns 401 without token"""
    resp = requests.post(f"{api_base}/api/leads/reveal/1", timeout=10)
    assert resp.status_code == 401


def test_reveal_insufficient_credits(api_base, client_token):
    """POST /api/leads/reveal/<id> returns 402 when balance=0 — skip if balance > 0"""
    # Check current balance first
    credits_resp = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    )
    if credits_resp.status_code != 200:
        pytest.skip("Cannot read client credits")
    balance = credits_resp.json().get("balance", 1)
    if balance > 0:
        pytest.skip(f"Client has {balance} credits — 402 test requires balance=0")
    # Balance is 0 — try revealing a lead
    resp = requests.post(
        f"{api_base}/api/leads/reveal/999999",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    )
    assert resp.status_code in (402, 404)  # 402 no credits, 404 lead not found


def test_reveal_success_deducts_credit(api_base, client_token):
    """POST /api/leads/reveal/<id> deducts 1 credit and returns email — skip if no leads or credits"""
    # Get initial balance
    credits_resp = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    )
    if credits_resp.status_code != 200:
        pytest.skip("Cannot read client credits")
    initial_balance = credits_resp.json().get("balance", 0)
    if initial_balance == 0:
        pytest.skip("Client has no credits — cannot test reveal deduction")

    # Find a lead to reveal via search
    search_resp = requests.get(
        f"{api_base}/api/leads/search",
        headers={"Authorization": f"Bearer {client_token}"},
        params={"per_page": 1},
        timeout=10,
    )
    if search_resp.status_code != 200:
        pytest.skip("Cannot access /api/leads/search")
    leads = search_resp.json().get("leads", [])
    if not leads:
        pytest.skip("No leads available in search results")

    lead_id = leads[0]["id"]
    already_revealed = leads[0].get("revealed", False)

    # Reveal the lead
    reveal_resp = requests.post(
        f"{api_base}/api/leads/reveal/{lead_id}",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    )
    assert reveal_resp.status_code == 200
    data = reveal_resp.json()
    assert "email" in data or "phone" in data  # at least one contact field returned

    # If not already revealed, check credit was deducted
    if not already_revealed:
        credits_after_resp = requests.get(
            f"{api_base}/api/client/credits",
            headers={"Authorization": f"Bearer {client_token}"},
            timeout=10,
        )
        assert credits_after_resp.status_code == 200
        after_balance = credits_after_resp.json().get("balance", initial_balance)
        assert after_balance == initial_balance - 1


def test_reveal_idempotent(api_base, client_token):
    """Re-revealing same lead does NOT deduct second credit"""
    # Get initial balance
    credits_resp = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    )
    if credits_resp.status_code != 200:
        pytest.skip("Cannot read client credits")
    initial_balance = credits_resp.json().get("balance", 0)
    if initial_balance == 0:
        pytest.skip("Client has no credits — cannot test idempotency")

    # Find a lead to reveal
    search_resp = requests.get(
        f"{api_base}/api/leads/search",
        headers={"Authorization": f"Bearer {client_token}"},
        params={"per_page": 1},
        timeout=10,
    )
    if search_resp.status_code != 200:
        pytest.skip("Cannot access /api/leads/search")
    leads = search_resp.json().get("leads", [])
    if not leads:
        pytest.skip("No leads available")

    lead_id = leads[0]["id"]

    # Reveal once
    r1 = requests.post(
        f"{api_base}/api/leads/reveal/{lead_id}",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    )
    assert r1.status_code == 200
    balance_after_first = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    ).json().get("balance")

    # Reveal same lead again — should NOT deduct another credit
    r2 = requests.post(
        f"{api_base}/api/leads/reveal/{lead_id}",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    )
    assert r2.status_code == 200
    balance_after_second = requests.get(
        f"{api_base}/api/client/credits",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=10,
    ).json().get("balance")

    assert balance_after_second == balance_after_first  # no second deduction
