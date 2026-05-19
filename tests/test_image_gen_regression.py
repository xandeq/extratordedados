"""
Regression tests — validate API contract, response schema and endpoint behavior.
Tests the live Flask API at API_BASE. Requires valid auth token + FAL_KEY.
Run: pytest tests/test_image_gen_regression.py -v
"""
import sys
import os
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'backend'))
import image_gen as _img_mod

API_BASE = "https://api.extratordedados.com.br"


def _read_local_secret(key: str) -> str:
    return _img_mod._load_secret(key)


@pytest.fixture(scope="session")
def auth_headers():
    """Get auth token from live API using credentials from local secrets."""
    admin_pass = _read_local_secret("ADMIN_PASSWORD") or _read_local_secret("DIAX_ADMIN_PASSWORD")
    if not admin_pass:
        pytest.skip("ADMIN_PASSWORD not found in ~/.claude/.secrets.env")
    resp = requests.post(
        f"{API_BASE}/api/login",
        json={"username": "admin", "password": admin_pass},
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(f"Login failed ({resp.status_code}): {resp.text[:200]}")
    token = resp.json().get("token")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def fal_available():
    key = _img_mod._get_fal_key()
    if not key:
        return False
    resp = requests.get(
        "https://fal.run/fal-ai/flux/schnell",
        headers={"Authorization": f"Key {key}"},
        timeout=5,
    )
    return resp.status_code != 401


# ── /api/images/models ────────────────────────────────────────────────────────
class TestModelsEndpoint:
    def test_returns_200(self, auth_headers):
        resp = requests.get(f"{API_BASE}/api/images/models", headers=auth_headers, timeout=10)
        assert resp.status_code == 200

    def test_returns_json(self, auth_headers):
        resp = requests.get(f"{API_BASE}/api/images/models", headers=auth_headers, timeout=10)
        assert resp.headers.get("content-type", "").startswith("application/json")

    def test_has_models_key(self, auth_headers):
        resp = requests.get(f"{API_BASE}/api/images/models", headers=auth_headers, timeout=10)
        body = resp.json()
        assert "models" in body

    def test_has_ten_models(self, auth_headers):
        resp = requests.get(f"{API_BASE}/api/images/models", headers=auth_headers, timeout=10)
        body = resp.json()
        assert len(body["models"]) == 10  # 7 FAL.AI + 3 OpenRouter

    def test_models_have_correct_schema(self, auth_headers):
        resp = requests.get(f"{API_BASE}/api/images/models", headers=auth_headers, timeout=10)
        for m in resp.json()["models"]:
            assert "key" in m
            assert "id" in m
            assert "name" in m
            assert "cost_usd" in m
            assert "supports_editing" in m

    def test_requires_auth(self):
        resp = requests.get(f"{API_BASE}/api/images/models", timeout=10)
        assert resp.status_code == 401

    def test_nano_banana_2_present(self, auth_headers):
        resp = requests.get(f"{API_BASE}/api/images/models", headers=auth_headers, timeout=10)
        keys = [m["key"] for m in resp.json()["models"]]
        assert "nano-banana-2" in keys

    def test_flux_schnell_present(self, auth_headers):
        resp = requests.get(f"{API_BASE}/api/images/models", headers=auth_headers, timeout=10)
        keys = [m["key"] for m in resp.json()["models"]]
        assert "flux-schnell" in keys


# ── /api/images/generate ──────────────────────────────────────────────────────
class TestGenerateEndpoint:
    def test_requires_auth(self):
        resp = requests.post(f"{API_BASE}/api/images/generate", json={"prompt": "test"}, timeout=10)
        assert resp.status_code == 401

    def test_missing_prompt_returns_400(self, auth_headers):
        resp = requests.post(f"{API_BASE}/api/images/generate", json={}, headers=auth_headers, timeout=10)
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_empty_prompt_returns_400(self, auth_headers):
        resp = requests.post(f"{API_BASE}/api/images/generate", json={"prompt": "  "}, headers=auth_headers, timeout=10)
        assert resp.status_code == 400

    def test_generate_returns_url_with_valid_key(self, auth_headers, fal_available):
        if not fal_available:
            pytest.skip("FAL_KEY invalid — update key to run generation tests")
        resp = requests.post(
            f"{API_BASE}/api/images/generate",
            json={"prompt": "simple red circle on white background", "model": "flux-schnell"},
            headers=auth_headers,
            timeout=60,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "url" in body
        assert body["url"].startswith("http")

    def test_generate_response_has_cost(self, auth_headers, fal_available):
        if not fal_available:
            pytest.skip("FAL_KEY invalid")
        resp = requests.post(
            f"{API_BASE}/api/images/generate",
            json={"prompt": "blue sky", "model": "flux-schnell"},
            headers=auth_headers,
            timeout=60,
        )
        body = resp.json()
        assert "cost_usd" in body
        assert isinstance(body["cost_usd"], (int, float))

    def test_generate_response_has_elapsed(self, auth_headers, fal_available):
        if not fal_available:
            pytest.skip("FAL_KEY invalid")
        resp = requests.post(
            f"{API_BASE}/api/images/generate",
            json={"prompt": "blue sky", "model": "flux-schnell"},
            headers=auth_headers,
            timeout=60,
        )
        body = resp.json()
        assert "elapsed_s" in body

    def test_invalid_model_falls_back_gracefully(self, auth_headers, fal_available):
        if not fal_available:
            pytest.skip("FAL_KEY invalid")
        resp = requests.post(
            f"{API_BASE}/api/images/generate",
            json={"prompt": "test image", "model": "nonexistent-model"},
            headers=auth_headers,
            timeout=90,
        )
        # Should succeed with fallback or return a clear error — not 500
        assert resp.status_code in (200, 400, 502)

    def test_aspect_ratio_16_9_accepted(self, auth_headers, fal_available):
        if not fal_available:
            pytest.skip("FAL_KEY invalid")
        resp = requests.post(
            f"{API_BASE}/api/images/generate",
            json={"prompt": "landscape photo", "model": "flux-schnell", "aspect_ratio": "16:9"},
            headers=auth_headers,
            timeout=60,
        )
        assert resp.status_code == 200


# ── /api/images/edit ──────────────────────────────────────────────────────────
class TestEditEndpoint:
    def test_requires_auth(self):
        resp = requests.post(f"{API_BASE}/api/images/edit", json={"image_url": "x", "prompt": "y"}, timeout=10)
        assert resp.status_code == 401

    def test_missing_image_url_returns_400(self, auth_headers):
        resp = requests.post(
            f"{API_BASE}/api/images/edit",
            json={"prompt": "make it blue"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_missing_prompt_returns_400(self, auth_headers):
        resp = requests.post(
            f"{API_BASE}/api/images/edit",
            json={"image_url": "https://example.com/img.jpg"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_edit_returns_url_with_valid_key(self, auth_headers, fal_available):
        if not fal_available:
            pytest.skip("FAL_KEY invalid")
        # First generate an image, then edit it
        gen_resp = requests.post(
            f"{API_BASE}/api/images/generate",
            json={"prompt": "plain white background with a small red dot", "model": "nano-banana-2"},
            headers=auth_headers,
            timeout=90,
        )
        assert gen_resp.status_code == 200
        source_url = gen_resp.json()["url"]

        edit_resp = requests.post(
            f"{API_BASE}/api/images/edit",
            json={"image_url": source_url, "prompt": "change the dot to blue", "model": "nano-banana-2"},
            headers=auth_headers,
            timeout=90,
        )
        assert edit_resp.status_code == 200
        body = edit_resp.json()
        assert "url" in body
        assert body["url"].startswith("http")


# ── /api/images/enhance-prompt ───────────────────────────────────────────────
class TestEnhancePromptEndpoint:
    def test_requires_auth(self):
        resp = requests.post(f"{API_BASE}/api/images/enhance-prompt", json={"prompt": "test"}, timeout=10)
        assert resp.status_code == 401

    def test_missing_prompt_returns_400(self, auth_headers):
        resp = requests.post(
            f"{API_BASE}/api/images/enhance-prompt",
            json={},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_returns_enhanced_and_original(self, auth_headers):
        resp = requests.post(
            f"{API_BASE}/api/images/enhance-prompt",
            json={"prompt": "cachorro fofo"},
            headers=auth_headers,
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "enhanced" in body
        assert "original" in body
        assert "used_llm" in body
        assert body["original"] == "cachorro fofo"

    def test_graceful_when_openrouter_unavailable(self, auth_headers):
        """Must return 200 even when OpenRouter key is missing (falls back gracefully)."""
        resp = requests.post(
            f"{API_BASE}/api/images/enhance-prompt",
            json={"prompt": "simple test"},
            headers=auth_headers,
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enhanced"] is not None
