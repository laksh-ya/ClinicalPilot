"""
LLM client utility — wraps OpenAI + Ollama with automatic fallback.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from openai import AsyncOpenAI

from backend.config import get_settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


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
            logger.warning(f"Ollama call failed ({e}), falling back to OpenAI")

    # OpenAI call
    result = await _openai_call(
        system_prompt, user_message,
        model=model or settings.openai_model,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )
    result["latency_ms"] = int((time.monotonic() - start) * 1000)
    return result


async def _openai_call(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    """Call OpenAI API."""
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

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
