"""
Image Generation Module — DIAX CRM
Providers: FAL.AI (7 models) + OpenRouter (image gen via DALL-E routing + prompt enhancement)
"""
import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

# ── Secret loader ─────────────────────────────────────────────────────────────
def _load_secret(key: str) -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    secrets_paths = [
        os.path.expanduser("~/.claude/.secrets.env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".deploy.env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
    ]
    for path in secrets_paths:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key}=") and not line.startswith("#"):
                        return line.split("=", 1)[1].strip()
        except FileNotFoundError:
            continue
    return ""

# ── Model registry ─────────────────────────────────────────────────────────────
MODELS = {
    "flux-schnell": {
        "id": "fal-ai/flux/schnell",
        "name": "FLUX Schnell",
        "provider": "fal",
        "cost_usd": 0.003,
        "description": "Ultra rápido, mais barato. Ideal para geração em volume.",
        "supports_editing": False,
        "default_input": {"num_inference_steps": 4, "image_size": "square_hd"},
    },
    "flux-lightning": {
        "id": "fal-ai/fast-lightning-sdxl",
        "name": "SDXL Lightning",
        "provider": "fal",
        "cost_usd": 0.003,
        "description": "Stable Diffusion XL em velocidade lightning. Ótimo custo-benefício.",
        "supports_editing": False,
        "default_input": {"image_size": "square_hd", "num_inference_steps": 4},
    },
    "flux2-flash": {
        "id": "fal-ai/flux-2/flash",
        "name": "Flux 2 Flash",
        "provider": "fal",
        "cost_usd": 0.01,
        "description": "FLUX 2 ultra rápido. Equilíbrio entre velocidade e qualidade.",
        "supports_editing": False,
        "default_input": {"image_size": "square_hd"},
    },
    "flux2-turbo": {
        "id": "fal-ai/flux-2/turbo",
        "name": "Flux 2 Turbo",
        "provider": "fal",
        "cost_usd": 0.015,
        "description": "FLUX 2 em modo turbo. Melhor qualidade que Flash.",
        "supports_editing": False,
        "default_input": {"image_size": "square_hd"},
    },
    "recraft-v3": {
        "id": "fal-ai/recraft/v3/text-to-image",
        "name": "Recraft V3",
        "provider": "fal",
        "cost_usd": 0.04,
        "description": "Melhor para design, marcas e tipografia. Excelente para marketing.",
        "supports_editing": False,
        "default_input": {"image_size": "square_hd", "style": "realistic_image"},
    },
    "nano-banana-2": {
        "id": "fal-ai/nano-banana-2",
        "name": "Nano Banana 2",
        "provider": "fal",
        "cost_usd": 0.08,
        "description": "Google Gemini Flash. Suporta edição de imagem nativa.",
        "supports_editing": True,
        "default_input": {},
    },
    "nano-banana-pro": {
        "id": "fal-ai/nano-banana-pro",
        "name": "Nano Banana Pro",
        "provider": "fal",
        "cost_usd": 0.15,
        "description": "Tipografia perfeita, edição avançada. Melhor qualidade Google.",
        "supports_editing": True,
        "default_input": {},
    },
}

DEFAULT_MODEL = "nano-banana-2"

# Fallback chain when primary model fails (FAL.AI only)
FALLBACK_CHAIN = ["flux-schnell", "flux-lightning", "flux2-flash"]

# ── OpenRouter image generation models ────────────────────────────────────────
OPENROUTER_IMAGE_MODELS = {
    "dalle3": {
        "id": "openai/dall-e-3",
        "name": "DALL-E 3",
        "provider": "openrouter",
        "cost_usd": 0.04,
        "description": "OpenAI DALL-E 3 via OpenRouter. Ótima qualidade, segue instruções precisamente.",
        "supports_editing": False,
        "sizes": ["1024x1024", "1024x1792", "1792x1024"],
        "default_size": "1024x1024",
    },
    "dalle2": {
        "id": "openai/dall-e-2",
        "name": "DALL-E 2",
        "provider": "openrouter",
        "cost_usd": 0.02,
        "description": "OpenAI DALL-E 2 via OpenRouter. Mais barato, bom para protótipos.",
        "supports_editing": False,
        "sizes": ["256x256", "512x512", "1024x1024"],
        "default_size": "512x512",
    },
    "sdxl-openrouter": {
        "id": "stability/stable-diffusion-xl-1024-v1-0",
        "name": "SDXL via OpenRouter",
        "provider": "openrouter",
        "cost_usd": 0.008,
        "description": "Stable Diffusion XL via OpenRouter. Ultra barato, bom para volume.",
        "supports_editing": False,
        "sizes": ["1024x1024"],
        "default_size": "1024x1024",
    },
}

OPENROUTER_IMAGE_API_URL = "https://openrouter.ai/api/v1/images/generations"

# ── OpenRouter config ──────────────────────────────────────────────────────────
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_ENHANCE_MODEL = "google/gemma-3-27b-it:free"
OPENROUTER_ENHANCE_FALLBACKS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-coder:free",
]

# ── Groq config (primary for prompt enhancement — free, fast, reliable) ────────
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_ENHANCE_MODEL = "llama-3.3-70b-versatile"

PROMPT_ENHANCE_SYSTEM = (
    "You are an expert at writing prompts for AI image generation. "
    "Translate the input to English if needed and enhance it to be more descriptive, "
    "vivid and specific. Focus on: lighting, style, mood, composition, details. "
    "Return ONLY the enhanced prompt, nothing else. Max 200 words."
)

# ── Helpers ────────────────────────────────────────────────────────────────────
def _get_fal_key() -> str:
    return _load_secret("FAL_KEY")

def _get_openrouter_key() -> str:
    return _load_secret("OPENROUTER_API_KEY")

def _get_groq_key() -> str:
    return _load_secret("GROQ_API_KEY")

def _fal_run(app_id: str, input_data: dict, timeout: int = 120) -> dict:
    """Call FAL.AI REST API synchronously."""
    key = _get_fal_key()
    if not key:
        raise ValueError("FAL_KEY not configured")

    resp = requests.post(
        f"https://fal.run/{app_id}",
        json=input_data,
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
        timeout=timeout,
    )
    if resp.status_code == 401:
        raise ValueError("FAL_KEY invalid or expired — update ~/.claude/.secrets.env")
    if resp.status_code == 402:
        raise ValueError("FAL.AI account out of credits")
    resp.raise_for_status()
    return resp.json()

def _extract_image_url(result: dict) -> str:
    """Extract first image URL from FAL.AI response (handles multiple response shapes)."""
    images = result.get("images") or result.get("image") or []
    if isinstance(images, dict):
        images = [images]
    if isinstance(images, list) and images:
        img = images[0]
        if isinstance(img, dict):
            return img.get("url") or img.get("image_url") or ""
        if isinstance(img, str):
            return img
    url = result.get("url") or result.get("image_url") or ""
    return url

# ── Public API ─────────────────────────────────────────────────────────────────
def get_models() -> list:
    """Return list of all available models (FAL.AI + OpenRouter) with metadata."""
    fal_models = [
        {
            "key": k,
            "id": v["id"],
            "name": v["name"],
            "provider": v["provider"],
            "cost_usd": v["cost_usd"],
            "description": v["description"],
            "supports_editing": v["supports_editing"],
        }
        for k, v in MODELS.items()
    ]
    or_models = [
        {
            "key": k,
            "id": v["id"],
            "name": v["name"],
            "provider": v["provider"],
            "cost_usd": v["cost_usd"],
            "description": v["description"],
            "supports_editing": v["supports_editing"],
        }
        for k, v in OPENROUTER_IMAGE_MODELS.items()
    ]
    return fal_models + or_models


def generate_image_openrouter(prompt: str, model_key: str = "dalle3",
                               aspect_ratio: str = "1:1", **kwargs) -> dict:
    """Generate image via OpenRouter (DALL-E 3, DALL-E 2, SDXL)."""
    key = _get_openrouter_key()
    if not key:
        raise ValueError("OPENROUTER_API_KEY not configured")

    model_key = model_key if model_key in OPENROUTER_IMAGE_MODELS else "dalle3"
    cfg = OPENROUTER_IMAGE_MODELS[model_key]

    size_map = {"1:1": cfg["default_size"], "16:9": "1792x1024", "9:16": "1024x1792"}
    size = size_map.get(aspect_ratio, cfg["default_size"])
    if size not in cfg["sizes"]:
        size = cfg["default_size"]

    t0 = time.time()
    resp = requests.post(
        OPENROUTER_IMAGE_API_URL,
        json={"model": cfg["id"], "prompt": prompt, "n": 1, "size": size},
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://extratordedados.com.br",
            "X-Title": "DIAX CRM",
        },
        timeout=60,
    )
    if resp.status_code == 401:
        raise ValueError("OPENROUTER_API_KEY invalid or expired")
    if resp.status_code == 402:
        raise ValueError("OpenRouter account out of credits")
    resp.raise_for_status()
    data = resp.json()

    images = data.get("data") or []
    url = images[0].get("url") or images[0].get("b64_json", "") if images else ""

    return {
        "url": url,
        "model": cfg["name"],
        "model_key": model_key,
        "model_id": cfg["id"],
        "cost_usd": cfg["cost_usd"],
        "elapsed_s": round(time.time() - t0, 2),
        "prompt_used": prompt,
        "prompt_enhanced": False,
        "fallback_used": False,
        "provider": "openrouter",
    }

def _call_llm_for_enhancement(api_url: str, model: str, headers: dict, prompt: str) -> str:
    """Call LLM API and return enhanced prompt text, or raise on failure."""
    resp = requests.post(
        api_url,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": PROMPT_ENHANCE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 300,
            "temperature": 0.7,
        },
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("LLM returned empty choices array")
    content = (choices[0].get("message") or {}).get("content", "")
    if not content:
        raise ValueError("Empty response from LLM")
    return content.strip()


def enhance_prompt(prompt: str) -> dict:
    """
    Enhance a prompt using LLM. Primary: Groq (free, fast). Fallback: OpenRouter.
    Returns {enhanced, original, used_llm, model?}.
    """
    # Try Groq first (free, fast, reliable)
    groq_key = _get_groq_key()
    if groq_key:
        try:
            enhanced = _call_llm_for_enhancement(
                GROQ_API_URL, GROQ_ENHANCE_MODEL,
                {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                prompt,
            )
            return {"enhanced": enhanced, "original": prompt, "used_llm": True, "model": GROQ_ENHANCE_MODEL}
        except Exception as e:
            logger.warning("Groq prompt enhancement failed: %s — trying OpenRouter", e)

    # Fallback: OpenRouter
    or_key = _get_openrouter_key()
    if not or_key:
        return {"enhanced": prompt, "original": prompt, "used_llm": False, "error": "No LLM key available"}

    for model in [OPENROUTER_ENHANCE_MODEL] + OPENROUTER_ENHANCE_FALLBACKS:
        try:
            enhanced = _call_llm_for_enhancement(
                OPENROUTER_API_URL, model,
                {
                    "Authorization": f"Bearer {or_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://extratordedados.com.br",
                    "X-Title": "DIAX CRM",
                },
                prompt,
            )
            return {"enhanced": enhanced, "original": prompt, "used_llm": True, "model": model}
        except Exception as e:
            logger.warning("OpenRouter model %s failed: %s", model, e)

    return {"enhanced": prompt, "original": prompt, "used_llm": False, "error": "All LLM providers failed"}

def generate_image(prompt: str, model_key: str = DEFAULT_MODEL, enhance: bool = False,
                   aspect_ratio: str = "1:1", provider: str = "auto", **kwargs) -> dict:
    """
    Generate image using FAL.AI.
    Returns {url, model, model_key, cost_usd, elapsed_s, prompt_used, enhanced, error?}
    """
    prompt = prompt[:2000]  # guard against oversized inputs
    # Route to OpenRouter if model_key is an OpenRouter model
    if model_key in OPENROUTER_IMAGE_MODELS:
        prompt_info = enhance_prompt(prompt) if enhance else {"enhanced": prompt, "original": prompt, "used_llm": False}
        return generate_image_openrouter(prompt_info["enhanced"], model_key=model_key, aspect_ratio=aspect_ratio, **kwargs)

    model_key = model_key if model_key in MODELS else DEFAULT_MODEL
    model_cfg = MODELS[model_key]

    prompt_info = enhance_prompt(prompt) if enhance else {"enhanced": prompt, "original": prompt, "used_llm": False}
    final_prompt = prompt_info["enhanced"]

    size_map = {"1:1": "square_hd", "16:9": "landscape_16_9", "9:16": "portrait_16_9", "4:3": "landscape_4_3"}
    image_size = size_map.get(aspect_ratio, "square_hd")

    input_data = {**model_cfg.get("default_input", {}), "prompt": final_prompt, "image_size": image_size}
    input_data.update(kwargs)

    attempts = [model_key] + [f for f in FALLBACK_CHAIN if f != model_key]
    last_error = None

    for attempt_key in attempts:
        cfg = MODELS[attempt_key]
        t0 = time.time()
        try:
            result = _fal_run(cfg["id"], {**cfg.get("default_input", {}), "prompt": final_prompt, "image_size": image_size})
            url = _extract_image_url(result)
            return {
                "url": url,
                "model": cfg["name"],
                "model_key": attempt_key,
                "model_id": cfg["id"],
                "cost_usd": cfg["cost_usd"],
                "elapsed_s": round(time.time() - t0, 2),
                "prompt_used": final_prompt,
                "prompt_enhanced": prompt_info["used_llm"],
                "fallback_used": attempt_key != model_key,
            }
        except ValueError as e:
            raise  # auth/config errors — don't retry
        except Exception as e:
            last_error = str(e)
            logger.warning("FAL model %s failed: %s — trying fallback", cfg["id"], e)
            continue

    return {"error": f"All models failed. Last error: {last_error}", "url": None}

def edit_image(image_url: str, prompt: str, model_key: str = "nano-banana-2", **kwargs) -> dict:
    """
    Edit an existing image using FAL.AI (only editing-capable models).
    Returns same shape as generate_image.
    """
    # SSRF guard: only allow https:// URLs pointing to known CDN/FAL domains
    _allowed_hosts = (
        "fal.media", "fal.run", "fal-cdn.com",
        "storage.googleapis.com", "cdn.openai.com",
        "extratordedados.com.br",
    )
    if not image_url.startswith("https://") or not any(h in image_url for h in _allowed_hosts):
        raise ValueError(f"image_url must be an https:// URL from a trusted host: {image_url[:80]}")

    model_key = model_key if model_key in MODELS else "nano-banana-2"
    if not MODELS[model_key]["supports_editing"]:
        model_key = "nano-banana-2"

    cfg = MODELS[model_key]
    t0 = time.time()
    input_data = {**cfg.get("default_input", {}), "prompt": prompt, "image_url": image_url}
    input_data.update(kwargs)

    result = _fal_run(cfg["id"], input_data)
    url = _extract_image_url(result)
    return {
        "url": url,
        "model": cfg["name"],
        "model_key": model_key,
        "model_id": cfg["id"],
        "cost_usd": cfg["cost_usd"],
        "elapsed_s": round(time.time() - t0, 2),
        "prompt_used": prompt,
        "source_image_url": image_url,
    }
