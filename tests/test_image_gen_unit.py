"""
Unit tests for image_gen module — all mocked, zero real API calls.
Runs without any API keys.
"""
import sys
import os
import pytest
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'backend'))
import image_gen


# ── Fixtures ──────────────────────────────────────────────────────────────────
FAKE_IMAGE_URL = "https://fal.media/files/test/generated_image_12345.jpg"

FAL_OK_RESPONSE = {
    "images": [{"url": FAKE_IMAGE_URL, "width": 1024, "height": 1024}],
    "seed": 42,
}

OPENROUTER_OK_RESPONSE = {
    "choices": [{"message": {"content": "A stunning professional photo with dramatic lighting"}}]
}


# ── get_models ────────────────────────────────────────────────────────────────
class TestGetModels:
    def test_returns_list(self):
        models = image_gen.get_models()
        assert isinstance(models, list)

    def test_has_ten_models(self):
        # 7 FAL.AI + 3 OpenRouter
        models = image_gen.get_models()
        assert len(models) == 10

    def test_model_has_required_fields(self):
        for m in image_gen.get_models():
            assert "key" in m
            assert "id" in m
            assert "name" in m
            assert "provider" in m
            assert "cost_usd" in m
            assert "description" in m
            assert "supports_editing" in m

    def test_has_fal_and_openrouter_providers(self):
        providers = {m["provider"] for m in image_gen.get_models()}
        assert "fal" in providers
        assert "openrouter" in providers

    def test_seven_fal_models(self):
        fal = [m for m in image_gen.get_models() if m["provider"] == "fal"]
        assert len(fal) == 7

    def test_three_openrouter_models(self):
        or_models = [m for m in image_gen.get_models() if m["provider"] == "openrouter"]
        assert len(or_models) == 3

    def test_nano_banana_2_supports_editing(self):
        models = {m["key"]: m for m in image_gen.get_models()}
        assert models["nano-banana-2"]["supports_editing"] is True

    def test_flux_schnell_does_not_support_editing(self):
        models = {m["key"]: m for m in image_gen.get_models()}
        assert models["flux-schnell"]["supports_editing"] is False

    def test_flux_schnell_is_cheapest(self):
        models = image_gen.get_models()
        costs = [m["cost_usd"] for m in models]
        cheapest = min(costs)
        schnell = next(m for m in models if m["key"] == "flux-schnell")
        assert schnell["cost_usd"] == cheapest

    def test_model_ids_are_fal_format(self):
        for m in image_gen.get_models():
            assert m["id"].startswith("fal-ai/") or "/" in m["id"]


# ── enhance_prompt ────────────────────────────────────────────────────────────
class TestEnhancePrompt:
    def test_returns_original_when_no_key(self):
        with patch.object(image_gen, '_get_groq_key', return_value=""):
            with patch.object(image_gen, '_get_openrouter_key', return_value=""):
                result = image_gen.enhance_prompt("foto de pessoa")
        assert result["original"] == "foto de pessoa"
        assert result["enhanced"] == "foto de pessoa"
        assert result["used_llm"] is False

    def test_uses_groq_when_key_present(self):
        with patch.object(image_gen, '_get_groq_key', return_value="gsk-test"):
            with patch('image_gen.requests.post') as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = OPENROUTER_OK_RESPONSE
                mock_resp.raise_for_status = MagicMock()
                mock_post.return_value = mock_resp
                result = image_gen.enhance_prompt("foto simples")
        assert result["used_llm"] is True
        assert "stunning" in result["enhanced"]

    def test_uses_openrouter_when_groq_fails(self):
        with patch.object(image_gen, '_get_groq_key', return_value="gsk-test"):
            with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
                with patch('image_gen.requests.post') as mock_post:
                    # First call (Groq) fails, second (OpenRouter) succeeds
                    fail_resp = MagicMock()
                    fail_resp.raise_for_status.side_effect = Exception("groq down")
                    ok_resp = MagicMock()
                    ok_resp.status_code = 200
                    ok_resp.json.return_value = OPENROUTER_OK_RESPONSE
                    ok_resp.raise_for_status = MagicMock()
                    mock_post.side_effect = [fail_resp, ok_resp]
                    result = image_gen.enhance_prompt("foto simples")
        assert result["used_llm"] is True
        assert "stunning" in result["enhanced"]

    def test_fallback_on_all_error(self):
        with patch.object(image_gen, '_get_groq_key', return_value="gsk-test"):
            with patch.object(image_gen, '_get_openrouter_key', return_value="sk-or-test"):
                with patch('image_gen.requests.post', side_effect=Exception("timeout")):
                    result = image_gen.enhance_prompt("some prompt")
        assert result["original"] == "some prompt"
        assert result["enhanced"] == "some prompt"
        assert result["used_llm"] is False
        assert "error" in result

    def test_returns_dict_with_required_keys(self):
        with patch.object(image_gen, '_get_groq_key', return_value=""):
            with patch.object(image_gen, '_get_openrouter_key', return_value=""):
                result = image_gen.enhance_prompt("test")
        assert "enhanced" in result
        assert "original" in result
        assert "used_llm" in result


# ── generate_image ────────────────────────────────────────────────────────────
class TestGenerateImage:
    def _mock_fal(self, response=FAL_OK_RESPONSE):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_returns_url_on_success(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()):
                result = image_gen.generate_image("a red apple")
        assert result["url"] == FAKE_IMAGE_URL

    def test_uses_default_model(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                image_gen.generate_image("test prompt")
                call_url = mock_post.call_args[0][0]
                assert image_gen.MODELS[image_gen.DEFAULT_MODEL]["id"] in call_url

    def test_uses_specified_model(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                image_gen.generate_image("test", model_key="flux-schnell")
                call_url = mock_post.call_args[0][0]
                assert "flux/schnell" in call_url

    def test_falls_back_to_default_on_unknown_model(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                result = image_gen.generate_image("test", model_key="nonexistent-model-xyz")
                # Should use default, not crash
                assert result.get("url") or result.get("error")

    def test_result_has_required_fields(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()):
                result = image_gen.generate_image("test")
        for field in ("url", "model", "model_key", "model_id", "cost_usd", "elapsed_s", "prompt_used"):
            assert field in result, f"Missing field: {field}"

    def test_elapsed_is_positive_float(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()):
                result = image_gen.generate_image("test")
        assert isinstance(result["elapsed_s"], float)
        assert result["elapsed_s"] >= 0

    def test_raises_on_missing_key(self):
        with patch.object(image_gen, '_get_fal_key', return_value=""):
            with pytest.raises(ValueError, match="FAL_KEY not configured"):
                image_gen.generate_image("test")

    def test_raises_on_invalid_key(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status = MagicMock()
        with patch.object(image_gen, '_get_fal_key', return_value="bad-key"):
            with patch('image_gen.requests.post', return_value=mock_resp):
                with pytest.raises(ValueError, match="invalid or expired"):
                    image_gen.generate_image("test")

    def test_fallback_chain_on_failure(self):
        call_count = {"n": 0}
        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("Model timeout")
            return self._mock_fal()
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', side_effect=side_effect):
                result = image_gen.generate_image("test", model_key="nano-banana-2")
        assert result.get("url") == FAKE_IMAGE_URL
        assert result.get("fallback_used") is True
        assert call_count["n"] == 2

    def test_enhance_flag_calls_openrouter(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch.object(image_gen, 'enhance_prompt') as mock_enhance:
                mock_enhance.return_value = {"enhanced": "enhanced prompt", "original": "p", "used_llm": True}
                with patch('image_gen.requests.post', return_value=self._mock_fal()):
                    result = image_gen.generate_image("simple prompt", enhance=True)
        mock_enhance.assert_called_once_with("simple prompt")

    def test_aspect_ratio_1_1(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                image_gen.generate_image("test", aspect_ratio="1:1")
                body = mock_post.call_args[1]["json"]
                assert body.get("image_size") == "square_hd"

    def test_aspect_ratio_16_9(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                image_gen.generate_image("test", aspect_ratio="16:9")
                body = mock_post.call_args[1]["json"]
                assert body.get("image_size") == "landscape_16_9"

    def test_returns_error_dict_when_all_models_fail(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', side_effect=Exception("all failed")):
                result = image_gen.generate_image("test")
        assert "error" in result
        assert result.get("url") is None

    def test_response_shape_matches_image_type(self):
        response_with_list = {"image": {"url": FAKE_IMAGE_URL}}
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal(response_with_list)):
                result = image_gen.generate_image("test")
        assert result["url"] == FAKE_IMAGE_URL


# ── edit_image ────────────────────────────────────────────────────────────────
class TestEditImage:
    def _mock_fal(self, url=FAKE_IMAGE_URL):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"images": [{"url": url}]}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_passes_image_url_to_api(self):
        source_url = "https://example.com/source.jpg"
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                image_gen.edit_image(source_url, "make it brighter")
                body = mock_post.call_args[1]["json"]
                assert body.get("image_url") == source_url

    def test_uses_editing_capable_model(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                image_gen.edit_image("https://x.com/img.jpg", "edit it", model_key="nano-banana-2")
                call_url = mock_post.call_args[0][0]
                assert "nano-banana" in call_url

    def test_falls_back_to_editing_model_when_non_editing_requested(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()) as mock_post:
                image_gen.edit_image("https://x.com/img.jpg", "edit it", model_key="flux-schnell")
                call_url = mock_post.call_args[0][0]
                assert "nano-banana" in call_url

    def test_result_includes_source_image_url(self):
        source_url = "https://example.com/source.jpg"
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()):
                result = image_gen.edit_image(source_url, "make brighter")
        assert result.get("source_image_url") == source_url

    def test_result_has_url(self):
        with patch.object(image_gen, '_get_fal_key', return_value="test-key"):
            with patch('image_gen.requests.post', return_value=self._mock_fal()):
                result = image_gen.edit_image("https://x.com/img.jpg", "edit it")
        assert result.get("url") == FAKE_IMAGE_URL


# ── _extract_image_url ────────────────────────────────────────────────────────
class TestExtractImageUrl:
    def test_images_list_of_dicts(self):
        r = {"images": [{"url": "https://x.com/a.jpg"}]}
        assert image_gen._extract_image_url(r) == "https://x.com/a.jpg"

    def test_image_single_dict(self):
        r = {"image": {"url": "https://x.com/b.jpg"}}
        assert image_gen._extract_image_url(r) == "https://x.com/b.jpg"

    def test_images_list_of_strings(self):
        r = {"images": ["https://x.com/c.jpg"]}
        assert image_gen._extract_image_url(r) == "https://x.com/c.jpg"

    def test_url_at_top_level(self):
        r = {"url": "https://x.com/d.jpg"}
        assert image_gen._extract_image_url(r) == "https://x.com/d.jpg"

    def test_empty_response(self):
        assert image_gen._extract_image_url({}) == ""
