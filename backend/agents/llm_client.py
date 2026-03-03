"""
LLM client utility — wraps OpenAI + Ollama + Groq with automatic fallback.

Priority: Local Ollama → OpenAI → Groq (fallback)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from openai import AsyncOpenAI

from backend.config import get_settings, get_effective

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# ── Groq free-tier limits ────────────────────────────────
GROQ_MAX_INPUT_CHARS = 18_000   # ~4.5K tokens — keeps prompt+response under 6K tokens
GROQ_MAX_OUTPUT_TOKENS = 2048   # Cap response size
GROQ_MAX_RETRIES = 4
GROQ_BASE_DELAY = 5.0          # seconds


def load_prompt(name: str) -> str:
    """Load a system prompt from the prompts/ directory."""
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text()
    logger.warning(f"Prompt file {name} not found at {path}")
    return ""


async def llm_call(
    system_prompt: str,
    user_message: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    json_mode: bool = True,
) -> dict[str, Any]:
    """
    Call LLM (OpenAI or Ollama) and return parsed JSON response.
    
    Returns: {"content": parsed_json_or_str, "model": str, "tokens": int, "latency_ms": int}
    """
    settings = get_settings()
    start = time.monotonic()

    # Try local LLM first if configured
    if settings.use_local_llm:
        try:
            result = await _ollama_call(
                system_prompt, user_message,
                model=model or settings.ollama_model,
                temperature=temperature,
            )
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            return result
        except Exception as e:
            logger.warning(f"Ollama call failed ({e}), falling back to cloud LLM")

    # Try OpenAI if API key is available
    openai_key = get_effective("openai_api_key")
    if openai_key:
        try:
            result = await _openai_call(
                system_prompt, user_message,
                model=model or settings.openai_model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            return result
        except Exception as e:
            logger.warning(f"OpenAI call failed ({e}), falling back to Groq")

    # Fallback to Groq — always use Groq model, ignore any OpenAI model name
    # Truncate messages and cap tokens for free-tier limits
    groq_key = get_effective("groq_api_key")
    if groq_key:
        truncated_system = _truncate_for_groq(system_prompt, GROQ_MAX_INPUT_CHARS // 3)
        truncated_user = _truncate_for_groq(user_message, (GROQ_MAX_INPUT_CHARS * 2) // 3)
        groq_max = min(max_tokens, GROQ_MAX_OUTPUT_TOKENS)
        try:
            result = await _groq_call(
                truncated_system, truncated_user,
                model=settings.groq_model,
                temperature=temperature,
                max_tokens=groq_max,
                json_mode=json_mode,
            )
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            return result
        except Exception as e:
            logger.error(f"Groq call also failed: {e}")
            raise

    raise RuntimeError(
        "No LLM provider available. Set OPENAI_API_KEY or GROQ_API_KEY in .env, "
        "or provide an OpenAI API key via the Settings panel."
    )


async def _openai_call(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    """Call OpenAI API."""
    api_key = get_effective("openai_api_key")
    client = AsyncOpenAI(api_key=api_key)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(**kwargs)
    content_str = response.choices[0].message.content or "{}"
    tokens = response.usage.total_tokens if response.usage else 0

    # Parse JSON
    try:
        content = json.loads(content_str)
    except json.JSONDecodeError:
        content = content_str

    return {"content": content, "model": model, "tokens": tokens}


async def _ollama_call(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
) -> dict[str, Any]:
    """Call Ollama local LLM."""
    settings = get_settings()
    url = f"{settings.ollama_base_url}/api/chat"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content_str = data.get("message", {}).get("content", "{}")
    try:
        content = json.loads(content_str)
    except json.JSONDecodeError:
        content = content_str

    tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
    return {"content": content, "model": model, "tokens": tokens}


def _truncate_for_groq(text: str, max_chars: int) -> str:
    """Truncate text to fit within Groq free-tier token limits."""
    if len(text) <= max_chars:
        return text
    logger.info(f"Truncating message from {len(text)} to {max_chars} chars for Groq")
    truncated = text[:max_chars]
    # Try to cut at a sentence/paragraph boundary
    for sep in ("\n\n", "\n", ". ", " "):
        idx = truncated.rfind(sep)
        if idx > max_chars * 0.7:
            truncated = truncated[:idx]
            break
    return truncated + "\n\n[... truncated for model context limits]"


async def _groq_call(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    max_tokens: int = 2048,
    json_mode: bool = True,
) -> dict[str, Any]:
    """Call Groq API with retry logic for rate limits (429/413)."""
    from groq import AsyncGroq

    api_key = get_effective("groq_api_key")
    client = AsyncGroq(api_key=api_key)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(GROQ_MAX_RETRIES):
        try:
            response = await client.chat.completions.create(**kwargs)
            content_str = response.choices[0].message.content or "{}"
            tokens = response.usage.total_tokens if response.usage else 0

            try:
                content = json.loads(content_str)
            except json.JSONDecodeError:
                content = content_str

            return {"content": content, "model": model, "tokens": tokens}

        except Exception as e:
            last_error = e
            error_code = getattr(e, "status_code", 0)

            if error_code == 413:
                # Payload too large — further truncate and retry
                logger.warning(f"Groq 413: payload too large (attempt {attempt + 1}). Truncating further.")
                current_sys = kwargs["messages"][0]["content"]
                current_usr = kwargs["messages"][1]["content"]
                kwargs["messages"][0]["content"] = current_sys[:len(current_sys) * 2 // 3]
                kwargs["messages"][1]["content"] = current_usr[:len(current_usr) * 2 // 3]
                kwargs["max_tokens"] = min(kwargs["max_tokens"], 1024)
                await asyncio.sleep(1)
                continue

            if error_code == 429:
                # Rate limited — back off
                delay = GROQ_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Groq 429: rate limited (attempt {attempt + 1}). Waiting {delay:.0f}s...")
                await asyncio.sleep(delay)
                continue

            # Non-retryable error
            raise

    raise last_error  # type: ignore[misc]
