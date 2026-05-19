"""
Unit tests for OpenRouter image generation — all mocked, no real API calls.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'backend'))
import image_gen

FAKE_IMAGE_URL = "https://oaidalleapiprodscus.blob.core.windows.net/private/test.png"

OR_OK_RESPONSE = {
    "data": [{"url": FAKE_IMAGE_URL}],
    "created": 1700000000,
}


def _mock_or_resp(data=OR_OK_RESPONSE, status=200):
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.json.return_value = data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ── get_models includes OpenRouter ─────────────────────────────────────────────
class TestGetModelsOpenRouter:
    def test_total_models_is_ten(self):
        # 7 FAL + 3 OpenRouter
        models = image_gen.get_models()
        assert len(models) == 10

    def test_openrouter_models_present(self):
        keys = [m["key"] for m in image_gen.get_models()]
        assert "dalle3" in keys
        assert "dalle2" in keys
        assert "sdxl-openrouter" in keys

    def test_openrouter_provider_field(self):
        models = {m["key"]: m for m in image_gen.get_models()}
        assert models["dalle3"]["provider"] == "openrouter"
        assert models["dalle2"]["provider"] == "openrouter"

    def test_dalle3_cost(self):
        models = {m["key"]: m for m in image_gen.get_models()}
        assert models["dalle3"]["cost_usd"] == 0.04

    def test_dalle2_cheaper_than_dalle3(self):
        models = {m["key"]: m for m in image_gen.get_models()}
        assert models["dalle2"]["cost_usd"] < models["dalle3"]["cost_usd"]

    def test_sdxl_openrouter_cheapest(self):
        or_models = [m for m in image_gen.get_models() if m["provider"] == "openrouter"]
        costs = [m["cost_usd"] for m in or_models]
        sdxl = next(m for m in or_models if m["key"] == "sdxl-openrouter")
        assert sdxl["cost_usd"] == min(costs)


# ── generate_image_openrouter ──────────────────────────────────────────────────
class TestGenerateImageOpenRouter:
    def test_returns_url_on_success(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()):
                result = image_gen.generate_image_openrouter("a red apple", model_key="dalle3")
        assert result["url"] == FAKE_IMAGE_URL

    def test_provider_field_is_openrouter(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()):
                result = image_gen.generate_image_openrouter("test", model_key="dalle3")
        assert result["provider"] == "openrouter"

    def test_result_has_required_fields(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()):
                result = image_gen.generate_image_openrouter("test", model_key="dalle3")
        for field in ("url", "model", "model_key", "model_id", "cost_usd", "elapsed_s", "prompt_used"):
            assert field in result, f"Missing: {field}"

    def test_raises_when_no_key(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value=""):
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY not configured"):
                image_gen.generate_image_openrouter("test", model_key="dalle3")

    def test_raises_on_invalid_key(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="bad"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp(status=401)):
                with pytest.raises(ValueError, match="invalid or expired"):
                    image_gen.generate_image_openrouter("test", model_key="dalle3")

    def test_dalle2_uses_correct_model_id(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()) as mock_post:
                image_gen.generate_image_openrouter("test", model_key="dalle2")
                body = mock_post.call_args[1]["json"]
                assert body["model"] == "openai/dall-e-2"

    def test_dalle3_uses_correct_model_id(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()) as mock_post:
                image_gen.generate_image_openrouter("test", model_key="dalle3")
                body = mock_post.call_args[1]["json"]
                assert body["model"] == "openai/dall-e-3"

    def test_defaults_to_dalle3_on_unknown_key(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()) as mock_post:
                image_gen.generate_image_openrouter("test", model_key="nonexistent")
                body = mock_post.call_args[1]["json"]
                assert body["model"] == image_gen.OPENROUTER_IMAGE_MODELS["dalle3"]["id"]

    def test_aspect_ratio_16_9_maps_to_landscape(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()) as mock_post:
                image_gen.generate_image_openrouter("test", model_key="dalle3", aspect_ratio="16:9")
                body = mock_post.call_args[1]["json"]
                assert body["size"] == "1792x1024"

    def test_aspect_ratio_9_16_maps_to_portrait(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()) as mock_post:
                image_gen.generate_image_openrouter("test", model_key="dalle3", aspect_ratio="9:16")
                body = mock_post.call_args[1]["json"]
                assert body["size"] == "1024x1792"

    def test_dalle2_size_clamped_to_valid(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()) as mock_post:
                # DALL-E 2 doesn't support 1792x1024 — should fall back to default
                image_gen.generate_image_openrouter("test", model_key="dalle2", aspect_ratio="16:9")
                body = mock_post.call_args[1]["json"]
                assert body["size"] in image_gen.OPENROUTER_IMAGE_MODELS["dalle2"]["sizes"]


# ── generate_image routes to OpenRouter ──────────────────────────────────────
class TestGenerateImageRoutesToOpenRouter:
    def test_dalle3_key_routes_to_openrouter(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()) as mock_post:
                result = image_gen.generate_image("a sunset", model_key="dalle3")
        assert result["provider"] == "openrouter"
        assert result["url"] == FAKE_IMAGE_URL

    def test_dalle2_key_routes_to_openrouter(self):
        with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
            with patch('image_gen.requests.post', return_value=_mock_or_resp()):
                result = image_gen.generate_image("test", model_key="dalle2")
        assert result["provider"] == "openrouter"
