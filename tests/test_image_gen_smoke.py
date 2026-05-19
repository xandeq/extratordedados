"""
Smoke tests — hit real FAL.AI and OpenRouter APIs.
Requires valid API keys in ~/.claude/.secrets.env or env vars.
Run: pytest tests/test_image_gen_smoke.py -v -m smoke
"""
import sys
import os
import pytest
import requests as http_requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'backend'))
import image_gen

pytestmark = pytest.mark.smoke

FAL_KEY = image_gen._get_fal_key()
OPENROUTER_KEY = image_gen._get_openrouter_key()

SIMPLE_PROMPT = "a red apple on a white marble table, professional product photo, studio lighting"


# ── FAL.AI smoke tests ────────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def check_fal_key():
    if not FAL_KEY:
        pytest.skip("FAL_KEY not configured — add to ~/.claude/.secrets.env")
    # Probe the key
    resp = http_requests.get(
        "https://fal.run/fal-ai/flux/schnell",
        headers={"Authorization": f"Key {FAL_KEY}"},
        timeout=5,
    )
    if resp.status_code == 401:
        pytest.skip("FAL_KEY is invalid/expired — generate a new key at fal.ai/dashboard/keys")


@pytest.mark.parametrize("model_key,model_id", [
    ("flux-schnell",   "fal-ai/flux/schnell"),
    ("flux-lightning", "fal-ai/fast-lightning-sdxl"),
    ("flux2-flash",    "fal-ai/flux-2/flash"),
    ("flux2-turbo",    "fal-ai/flux-2/turbo"),
    ("recraft-v3",     "fal-ai/recraft/v3/text-to-image"),
    ("nano-banana-2",  "fal-ai/nano-banana-2"),
    ("nano-banana-pro","fal-ai/nano-banana-pro"),
])
def test_fal_model_generates_image(model_key, model_id):
    """Each FAL.AI model must return a valid image URL."""
    result = image_gen.generate_image(SIMPLE_PROMPT, model_key=model_key)
    assert "error" not in result or result.get("url"), f"Model {model_key} failed: {result.get('error')}"
    assert result.get("url"), f"No URL returned for {model_key}: {result}"
    assert result["url"].startswith("http"), f"URL is not HTTP: {result['url']}"
    assert result["model_key"] in (model_key, *image_gen.FALLBACK_CHAIN), \
        f"Unexpected model used: {result['model_key']}"


def test_fal_flux_schnell_is_fast():
    """Flux Schnell must complete in under 30 seconds."""
    result = image_gen.generate_image(SIMPLE_PROMPT, model_key="flux-schnell")
    assert result.get("url"), f"Failed: {result.get('error')}"
    assert result["elapsed_s"] < 30, f"Too slow: {result['elapsed_s']}s"


def test_fal_aspect_ratio_16_9():
    """16:9 aspect ratio must be accepted without error."""
    result = image_gen.generate_image(SIMPLE_PROMPT, model_key="flux-schnell", aspect_ratio="16:9")
    assert result.get("url"), f"Failed: {result.get('error')}"


def test_fal_aspect_ratio_9_16():
    result = image_gen.generate_image(SIMPLE_PROMPT, model_key="flux-schnell", aspect_ratio="9:16")
    assert result.get("url"), f"Failed: {result.get('error')}"


def test_fal_generate_with_prompt_enhancement():
    """generate with enhance=True must use OpenRouter and still return image."""
    if not OPENROUTER_KEY:
        pytest.skip("OPENROUTER_API_KEY not set — skipping enhancement test")
    result = image_gen.generate_image("maçã vermelha bonita", model_key="flux-schnell", enhance=True)
    assert result.get("url"), f"Failed: {result.get('error')}"
    assert result.get("prompt_enhanced") is True


def test_fal_nano_banana_2_edit_image():
    """Nano Banana 2 must edit an existing image."""
    gen = image_gen.generate_image(SIMPLE_PROMPT, model_key="nano-banana-2")
    assert gen.get("url"), f"Generate failed: {gen.get('error')}"
    edit = image_gen.edit_image(gen["url"], "make the apple golden", model_key="nano-banana-2")
    assert edit.get("url"), f"Edit failed: {edit.get('error')}"
    assert edit["url"].startswith("http")


def test_fal_fallback_on_intentional_model_error():
    """When primary model fails, fallback chain must recover."""
    import image_gen as ig
    original_fal_run = ig._fal_run
    call_count = {"n": 0}

    def patched_fal_run(app_id, input_data, timeout=120):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("Simulated first model failure")
        return original_fal_run(app_id, input_data, timeout)

    import unittest.mock as mock
    with mock.patch.object(ig, '_fal_run', side_effect=patched_fal_run):
        result = ig.generate_image(SIMPLE_PROMPT, model_key="nano-banana-2")

    assert result.get("url"), f"Fallback failed: {result.get('error')}"
    assert result.get("fallback_used") is True
    assert call_count["n"] >= 2


# ── OpenRouter smoke tests ────────────────────────────────────────────────────
class TestOpenRouterSmoke:
    @pytest.fixture(autouse=True)
    def require_openrouter(self):
        if not OPENROUTER_KEY:
            pytest.skip("OPENROUTER_API_KEY not configured")

    def test_enhance_prompt_in_portuguese(self):
        result = image_gen.enhance_prompt("foto profissional de um executivo sorrindo")
        assert result["used_llm"] is True
        assert len(result["enhanced"]) > 20
        assert result["original"] == "foto profissional de um executivo sorrindo"

    def test_enhance_prompt_returns_english(self):
        result = image_gen.enhance_prompt("cachorro fofo brincando no parque")
        assert result["used_llm"] is True
        # Enhanced prompt should be in English or at least improved
        enhanced = result["enhanced"].lower()
        assert any(word in enhanced for word in ["dog", "puppy", "park", "playing", "cachorro"])

    def test_enhance_prompt_is_longer(self):
        short = "apple"
        result = image_gen.enhance_prompt(short)
        if result["used_llm"]:
            assert len(result["enhanced"]) > len(short)

    def test_enhance_prompt_no_key_graceful(self):
        import unittest.mock as mock
        with mock.patch.object(image_gen, '_get_openrouter_key', return_value=""):
            result = image_gen.enhance_prompt("test")
        assert result["used_llm"] is False
        assert result["enhanced"] == "test"
