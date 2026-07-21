"""
LiteLLM router — turns a Profile into a LiteLLM call, with robust cross-provider
JSON parsing so OpenAI / Groq / Ollama / others all yield clean structured output.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .registry import Profile
from .secrets import resolve_secret, resolve_base_url

logger = logging.getLogger(__name__)

# Groq free-tier guards (only applied to groq profiles)
GROQ_MAX_INPUT_CHARS = 18_000
GROQ_MAX_OUTPUT_TOKENS = 2048


def litellm_model_string(profile: Profile) -> str:
    """Map a profile to the LiteLLM model identifier."""
    p = profile.provider
    m = profile.model
    if p == "ollama":
        return f"ollama_chat/{m}"
    if p == "groq":
        return f"groq/{m}"
    if p == "anthropic":
        return f"anthropic/{m}"
    if p == "azure":
        return f"azure/{m}"
    if p == "openai_compatible":
        return f"openai/{m}"  # LiteLLM: openai/<model> + api_base hits any OpenAI-style server
    return m  # plain OpenAI


def build_call_args(
    profile: Profile,
    system_prompt: str,
    user_message: str,
    *,
    json_mode: Optional[bool] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Assemble kwargs for litellm.acompletion from a profile + overrides."""
    prm = profile.params
    use_json = prm.json_mode if json_mode is None else json_mode
    temp = prm.temperature if temperature is None else temperature
    mtok = prm.max_tokens if max_tokens is None else max_tokens

    # Groq free-tier: truncate input + cap output
    if profile.provider == "groq":
        system_prompt = _truncate(system_prompt, GROQ_MAX_INPUT_CHARS // 3)
        user_message = _truncate(user_message, (GROQ_MAX_INPUT_CHARS * 2) // 3)
        mtok = min(mtok, GROQ_MAX_OUTPUT_TOKENS)

    args: dict[str, Any] = {
        "model": litellm_model_string(profile),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temp,
        "max_tokens": mtok,
    }

    # Stop sequences. Local models (Ollama) and OpenAI-compatible gateways serving open
    # models (Gemma/MedGemma, Llama, Qwen…) often ship without a stop token configured,
    # so they generate until max_tokens on every call — the classic "runs forever" hang.
    # Default in the common turn-end markers for those providers; hosted APIs (openai,
    # groq, anthropic) already stop correctly and are left alone unless overridden.
    stop = prm.stop
    if stop is None and profile.provider in ("ollama", "openai_compatible"):
        stop = ["<end_of_turn>", "<|im_end|>", "<|eot_id|>"]
    if stop:
        args["stop"] = stop

    # base_url: profile value, overridable by a hardcoded/env url ref
    base_url = resolve_base_url(profile.base_url, profile.base_url)
    if base_url:
        args["api_base"] = base_url

    # api key (may be None for local ollama)
    key = resolve_secret(profile.api_key_ref)
    if key:
        args["api_key"] = key

    # JSON grammar constraint (response_format) is SEPARATE from wanting JSON back.
    # We only constrain the model when the caller wants JSON *and* the profile allows a
    # grammar (prm.json_mode). Reasoning models (e.g. MedGemma 1.5, which emits a
    # <unused94>…thought…<unused95> block) stall or slow badly under grammar — set their
    # profile json_mode=false so the model generates freely; we still parse JSON out of the
    # reply via parse_content(). Hosted APIs keep grammar on for reliability.
    if use_json and prm.json_mode:
        args["response_format"] = {"type": "json_object"}

    return args


# ── Robust JSON extraction ──────────────────────────────────────────────────
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
# Special/control tokens that leak into plain-text output from local chat templates.
_SPECIAL_TOKEN_RE = re.compile(
    r"</?(?:start_of_turn|end_of_turn|eos|bos|pad|start_of_image|end_of_image|unused\d+)>"
)


def strip_model_artifacts(text: str) -> str:
    """Remove reasoning blocks and stray special tokens from a model reply.

    Reasoning models (e.g. MedGemma 1.5) emit a private chain-of-thought wrapped in
    <unused94>…thought…<unused95> *before* the real answer. Keep only what follows the
    last <unused95>, then drop any lingering control tokens.
    """
    if not text:
        return text
    if "<unused95>" in text:
        text = text.rsplit("<unused95>", 1)[-1]
    # also handle explicit <thought>…</thought> style if a template uses it
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = _SPECIAL_TOKEN_RE.sub("", text)
    # a leading bare "model" / "thought" role echo
    text = re.sub(r"^\s*(?:model|thought)\s*\n", "", text)
    return text.strip()


def parse_content(content_str: str, json_mode: bool) -> Any:
    """Best-effort parse of a model reply into a dict; falls back to the raw string.

    Handles the ways non-OpenAI providers deviate: reasoning-model thought blocks,
    markdown code fences, prose wrapped around the JSON, trailing commas, and arrays.
    """
    content_str = strip_model_artifacts(content_str or "")
    if not json_mode:
        return content_str
    if not content_str or not content_str.strip():
        return {}

    text = content_str.strip()

    # 1) direct parse (OpenAI json_mode path)
    parsed = _try_json(text)
    if parsed is not None:
        return parsed

    # 2) strip a ```json ... ``` fence
    fence = _FENCE_RE.search(text)
    if fence:
        parsed = _try_json(fence.group(1))
        if parsed is not None:
            return parsed

    # 3) slice from the first { or [ to its matching last } or ]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            parsed = _try_json(candidate)
            if parsed is not None:
                return parsed
            # 4) repair trailing commas, then retry
            parsed = _try_json(_TRAILING_COMMA_RE.sub(r"\1", candidate))
            if parsed is not None:
                return parsed

    logger.warning("Could not parse JSON from model reply (%d chars); returning raw text", len(text))
    return content_str


def _try_json(s: str) -> Any:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for sep in ("\n\n", "\n", ". ", " "):
        idx = truncated.rfind(sep)
        if idx > max_chars * 0.7:
            truncated = truncated[:idx]
            break
    return truncated + "\n\n[... truncated for model context limits]"
