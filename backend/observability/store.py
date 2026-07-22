"""
Observability store — records one trace per LLM attempt.

Layers:
  * in-memory ring buffer (fast dashboard reads)
  * SQLite (durable history across restarts)
  * optional external export (Langfuse / LangSmith) — best-effort, never blocking.

Recording is fire-and-forget: a store failure must never break a clinical call.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _trim_messages(messages: Optional[list]) -> Optional[str]:
    """Serialize request messages (system+user) to JSON, trimming each to keep traces light."""
    if not messages:
        return None
    try:
        trimmed = [{"role": m.get("role", ""), "content": (m.get("content") or "")[:4000]}
                   for m in messages]
        return json.dumps(trimmed)[:9000]
    except Exception:
        return None

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "observability.db"

_BUFFER_MAX = 5000
_buffer: deque[dict] = deque(maxlen=_BUFFER_MAX)
_lock = threading.Lock()
_db_ready = False


def _init_db() -> None:
    global _db_ready
    if _db_ready:
        return
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS traces (
                id TEXT PRIMARY KEY, ts TEXT, request_id TEXT, role TEXT,
                profile TEXT, provider TEXT, model TEXT, base_url TEXT,
                debate_round INTEGER, tokens_in INTEGER, tokens_out INTEGER,
                tokens_total INTEGER, latency_ms INTEGER, cost_usd REAL,
                success INTEGER, error TEXT, fallback_index INTEGER,
                request_json TEXT, response_text TEXT, meta_json TEXT
            )
            """
        )
        # Migrate older DBs that predate the payload columns.
        for col, decl in (("request_json", "TEXT"), ("response_text", "TEXT"), ("meta_json", "TEXT")):
            try:
                conn.execute(f"ALTER TABLE traces ADD COLUMN {col} {decl}")
            except Exception:
                pass  # column already exists
        conn.commit()
        conn.close()
        _db_ready = True
    except Exception as e:
        logger.warning("Observability DB init failed: %s", e)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def record_trace(
    *,
    role: str,
    profile: str,
    provider: str,
    model: str,
    base_url: Optional[str] = None,
    request_id: Optional[str] = None,
    debate_round: Optional[int] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    cost_usd: Optional[float] = None,
    success: bool = True,
    error: Optional[str] = None,
    fallback_index: int = 0,
    persist: bool = True,
    request_messages: Optional[list] = None,
    response_text: Optional[str] = None,
    meta: Optional[dict] = None,
) -> dict:
    """Record a single LLM attempt. Returns the trace dict (best-effort)."""
    trace = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id or "",
        "role": role,
        "profile": profile,
        "provider": provider,
        "model": model,
        "base_url": base_url or "",
        "debate_round": debate_round,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "tokens_total": int((tokens_in or 0) + (tokens_out or 0)),
        "latency_ms": int(latency_ms or 0),
        "cost_usd": cost_usd,
        "success": bool(success),
        "error": (error or "")[:500] or None,
        "fallback_index": fallback_index,
        "request_json": _trim_messages(request_messages),
        "response_text": (response_text or "")[:8000] or None,
        "meta_json": (json.dumps(meta)[:6000] if meta else None),
    }
    try:
        with _lock:
            _buffer.append(trace)
        if persist:
            _persist(trace)
        _export(trace)
    except Exception as e:  # never propagate
        logger.debug("record_trace failed: %s", e)
    return trace


def _persist(trace: dict) -> None:
    try:
        _init_db()
        if not _db_ready:
            return
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            """INSERT OR REPLACE INTO traces
               (id,ts,request_id,role,profile,provider,model,base_url,
                debate_round,tokens_in,tokens_out,tokens_total,latency_ms,
                cost_usd,success,error,fallback_index,request_json,response_text,meta_json)
               VALUES
               (:id,:ts,:request_id,:role,:profile,:provider,:model,:base_url,
                :debate_round,:tokens_in,:tokens_out,:tokens_total,:latency_ms,
                :cost_usd,:success,:error,:fallback_index,:request_json,:response_text,:meta_json)""",
            {**trace, "success": 1 if trace["success"] else 0},
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("persist failed: %s", e)


def _export(trace: dict) -> None:
    """Optional external export (Langfuse / LangSmith). Off unless configured."""
    try:
        from backend.llm.registry import load_config
        obs = load_config().observability
        if not (obs.langfuse or obs.langsmith):
            return
        # External SDKs are optional; import lazily and swallow if absent.
        if obs.langsmith:
            import os
            if os.environ.get("LANGSMITH_API_KEY"):
                # LangSmith reads env + auto-instruments; nothing to push manually here.
                pass
        if obs.langfuse:
            try:
                from langfuse import Langfuse  # type: ignore
                lf = Langfuse()
                lf.trace(
                    name=f"{trace['role']}:{trace['model']}",
                    metadata=trace,
                )
            except Exception:
                pass
    except Exception:
        pass


# ── Reads (dashboard) ────────────────────────────────────────────────────────
def _all_traces() -> list[dict]:
    """In-memory buffer, newest last. Backfilled from SQLite on first read."""
    with _lock:
        if _buffer:
            return list(_buffer)
    # cold start: pull recent history from SQLite
    rows = _load_from_db(limit=_BUFFER_MAX)
    with _lock:
        for r in rows:
            _buffer.append(r)
        return list(_buffer)


def _load_from_db(limit: int = 500, request_id: str = "", role: str = "") -> list[dict]:
    try:
        _init_db()
        if not _db_ready:
            return []
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM traces"
        clauses, params = [], []
        if request_id:
            clauses.append("request_id = ?"); params.append(request_id)
        if role:
            clauses.append("role = ?"); params.append(role)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
        rows = [dict(r) for r in conn.execute(q, params).fetchall()]
        conn.close()
        for r in rows:
            r["success"] = bool(r["success"])
        rows.reverse()  # oldest first, matching buffer order
        return rows
    except Exception as e:
        logger.debug("load_from_db failed: %s", e)
        return []


def get_traces(limit: int = 200, request_id: str = "", role: str = "") -> list[dict]:
    if request_id or role:
        # filtered reads go to SQLite for completeness
        rows = _load_from_db(limit=limit, request_id=request_id, role=role)
        if rows:
            return rows
        data = [t for t in _all_traces()
                if (not request_id or t["request_id"] == request_id)
                and (not role or t["role"] == role)]
        return data[-limit:]
    return list(_all_traces())[-limit:]


def get_summary() -> dict:
    data = _all_traces()
    total = len(data)
    ok = sum(1 for t in data if t["success"])
    errors = total - ok
    tokens = sum(t["tokens_total"] for t in data)
    cost = sum(t["cost_usd"] or 0 for t in data)
    latencies = [t["latency_ms"] for t in data if t["success"] and t["latency_ms"]]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0

    def _bucket(key: str) -> dict:
        out: dict[str, dict] = {}
        for t in data:
            k = t.get(key) or "unknown"
            b = out.setdefault(k, {"calls": 0, "errors": 0, "tokens": 0, "latency_sum": 0, "latency_n": 0})
            b["calls"] += 1
            if not t["success"]:
                b["errors"] += 1
            b["tokens"] += t["tokens_total"]
            if t["success"] and t["latency_ms"]:
                b["latency_sum"] += t["latency_ms"]
                b["latency_n"] += 1
        for b in out.values():
            b["avg_latency_ms"] = int(b["latency_sum"] / b["latency_n"]) if b["latency_n"] else 0
            del b["latency_sum"]; del b["latency_n"]
        return out

    # Per-debate-round breakdown (only rounds that were actually recorded).
    def _round_bucket() -> dict:
        out: dict[str, dict] = {}
        for t in data:
            r = t.get("debate_round")
            if r is None:
                continue
            k = f"Round {r}"
            b = out.setdefault(k, {"calls": 0, "errors": 0, "tokens": 0, "latency_sum": 0, "latency_n": 0})
            b["calls"] += 1
            if not t["success"]:
                b["errors"] += 1
            b["tokens"] += t["tokens_total"]
            if t["success"] and t["latency_ms"]:
                b["latency_sum"] += t["latency_ms"]
                b["latency_n"] += 1
        for b in out.values():
            b["avg_latency_ms"] = int(b["latency_sum"] / b["latency_n"]) if b["latency_n"] else 0
            del b["latency_sum"]; del b["latency_n"]
        # keep rounds in numeric order
        return {k: out[k] for k in sorted(out, key=lambda s: int(s.split()[-1]))}

    return {
        "total_calls": total,
        "success": ok,
        "errors": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "total_tokens": tokens,
        "est_cost_usd": round(cost, 4),
        "avg_latency_ms": avg_latency,
        "by_agent": _bucket("role"),
        "by_provider": _bucket("provider"),
        "by_model": _bucket("model"),
        "by_round": _round_bucket(),
        "last_request_id": data[-1]["request_id"] if data else "",
    }


def clear() -> None:
    with _lock:
        _buffer.clear()
    try:
        _init_db()
        if _db_ready:
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("DELETE FROM traces")
            conn.commit()
            conn.close()
    except Exception as e:
        logger.debug("clear failed: %s", e)
