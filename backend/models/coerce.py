"""
Coercion helpers for messy LLM output.

Small local models (e.g. MedGemma 4B) don't reliably honor a JSON schema: risk scores
come back as numbers/objects/strings, confidence as free text, ESI as "ESI 3", and lists
sometimes as bare strings. These helpers normalize such values so Pydantic validation
never crashes on real-world model output.
"""

from __future__ import annotations

import re
from typing import Any

_CONF = {"high", "medium", "low"}


def coerce_confidence(v: Any) -> str:
    """Map anything to 'high' | 'medium' | 'low' (default 'medium')."""
    if v is None:
        return "medium"
    s = str(v).strip().lower()
    if s in _CONF:
        return s
    # Check LOW first — 'uncertain'/'unlikely' contain 'certain'/'likely' as substrings.
    if any(w in s for w in ("low", "weak", "uncertain", "unlikely", "improbable", "poor", "doubtful")):
        return "low"
    if any(w in s for w in ("high", "very likely", "most likely", "likely", "strong", "definite", "certain", "probable")):
        return "high"
    if "moderate" in s or "medium" in s or "possible" in s:
        return "medium"
    return "medium"


def coerce_str_dict(v: Any) -> dict[str, str]:
    """Normalize any shape into a flat {str: str} mapping (for risk_scores)."""
    if v is None or v == "":
        return {}
    if isinstance(v, dict):
        out: dict[str, str] = {}
        for k, val in v.items():
            out[str(k)] = _flatten_scalar(val)
        return out
    if isinstance(v, list):
        out = {}
        for i, item in enumerate(v):
            if isinstance(item, dict):
                name = (item.get("name") or item.get("score") or item.get("type")
                        or item.get("label") or f"score_{i + 1}")
                value = (item.get("value") or item.get("result") or item.get("interpretation")
                         or item.get("risk") or _flatten_scalar(item))
                out[str(name)] = _flatten_scalar(value)
            else:
                out[f"score_{i + 1}"] = str(item)
        return out
    # a bare string / number
    return {"summary": str(v)}


def _flatten_scalar(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(_flatten_scalar(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_flatten_scalar(val)}" for k, val in v.items())
    return str(v)


def coerce_opt_int(v: Any) -> int | None:
    """Extract an int from ints or strings like 'ESI 3' / '3 (urgent)'."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    m = re.search(r"-?\d+", str(v))
    return int(m.group()) if m else None


def coerce_str(v: Any) -> str:
    """Coerce to a string, joining lists/dicts readably."""
    return _flatten_scalar(v)


def coerce_str_list(v: Any) -> list[str]:
    """Coerce to a list of strings."""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [_flatten_scalar(x) for x in v if x not in (None, "")]
    return [str(v)]


def coerce_bool(v: Any) -> bool:
    """Coerce free-text/booleans to a bool (default False)."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "yes", "y", "1", "reached", "consensus", "agreed"):
        return True
    if any(w in s for w in ("no consensus", "not reached", "disagree", "false", "no")):
        return False
    return s in ("true", "yes")
