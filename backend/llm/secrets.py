"""
Secret resolution — hardcode OR ask.

Resolution order for any logical key ref (e.g. "GROQ_API_KEY"):

    1. Hardcoded  → config/secrets.local.py  HARDCODED_KEYS / HARDCODED_BASE_URLS
    2. Hardcoded  → environment / .env
    3. Runtime    → value the user typed into the UI this session (memory only)
    4. Missing    → resolve_secret returns None; callers raise NeedsKey so the UI asks.

If a key is hardcoded (1 or 2) it is used and the user is never prompted.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SECRETS_FILE = PROJECT_ROOT / "config" / "secrets.local.py"

# ── Runtime overrides (in-memory only, set via the UI) ──────────────────────
_runtime_secrets: dict[str, str] = {}

# ── Hardcoded values loaded from config/secrets.local.py (cached) ───────────
_hardcoded_keys: dict[str, str] | None = None
_hardcoded_urls: dict[str, str] | None = None


class NeedsKey(Exception):
    """Raised when a required secret is not hardcoded and not provided at runtime."""

    def __init__(self, key_ref: str, profile_id: str = ""):
        self.key_ref = key_ref
        self.profile_id = profile_id
        super().__init__(f"Missing API key '{key_ref}' for profile '{profile_id}'")


def _load_hardcoded() -> None:
    """Load config/secrets.local.py once, if it exists."""
    global _hardcoded_keys, _hardcoded_urls
    if _hardcoded_keys is not None:
        return
    _hardcoded_keys, _hardcoded_urls = {}, {}
    if not _SECRETS_FILE.exists():
        return
    try:
        spec = importlib.util.spec_from_file_location("cp_secrets_local", _SECRETS_FILE)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _hardcoded_keys = {k: str(v) for k, v in getattr(mod, "HARDCODED_KEYS", {}).items() if v}
        _hardcoded_urls = {k: str(v) for k, v in getattr(mod, "HARDCODED_BASE_URLS", {}).items() if v}
        if _hardcoded_keys:
            logger.info("Loaded %d hardcoded key(s) from secrets.local.py", len(_hardcoded_keys))
    except Exception as e:  # never let a bad secrets file crash the app
        logger.warning("Failed to load config/secrets.local.py: %s", e)


def is_hardcoded(key_ref: str) -> bool:
    """True if the key is baked in (secrets file or env) — the user is never asked."""
    if not key_ref:
        return False
    _load_hardcoded()
    return bool(_hardcoded_keys.get(key_ref)) or bool(os.environ.get(key_ref))


def resolve_secret(key_ref: Optional[str]) -> Optional[str]:
    """Return the effective value for a key ref, or None if it must be asked for."""
    if not key_ref:
        return None
    _load_hardcoded()
    # 1 & 2: hardcoded (file or env) wins outright
    if _hardcoded_keys.get(key_ref):
        return _hardcoded_keys[key_ref]
    if os.environ.get(key_ref):
        return os.environ[key_ref]
    # 3: runtime override entered in the UI
    if _runtime_secrets.get(key_ref):
        return _runtime_secrets[key_ref]
    return None


def resolve_base_url(url_ref: Optional[str], fallback: Optional[str]) -> Optional[str]:
    """Base-URL override by logical name (HARDCODED_BASE_URLS / env), else the fallback."""
    if url_ref:
        _load_hardcoded()
        if _hardcoded_urls.get(url_ref):
            return _hardcoded_urls[url_ref]
        if os.environ.get(url_ref):
            return os.environ[url_ref]
        if _runtime_secrets.get(url_ref):
            return _runtime_secrets[url_ref]
    return fallback


def set_runtime_secret(key_ref: str, value: str) -> None:
    """Store a key entered via the UI (memory only, not persisted)."""
    if key_ref and value:
        _runtime_secrets[key_ref] = value.strip()
        logger.info("Runtime secret set for '%s'", key_ref)


def secret_status(key_ref: Optional[str]) -> str:
    """One of: 'none' (no ref needed), 'hardcoded', 'runtime', 'missing'."""
    if not key_ref:
        return "none"
    _load_hardcoded()
    if _hardcoded_keys.get(key_ref) or os.environ.get(key_ref):
        return "hardcoded"
    if _runtime_secrets.get(key_ref):
        return "runtime"
    return "missing"
