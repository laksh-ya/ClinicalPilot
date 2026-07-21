# ClinicalPilot — Model System & Observability Rebuild Plan

> Status: **PLAN / SPEC ONLY** — nothing here is implemented yet.
> Goal: replace the single hardcoded provider chain with a configurable, per-agent
> model system (LiteLLM-backed), add a real observability stack, expose debate-round
> and routing controls, and de-brand the provider names for a polished product feel.

---

## 0. Design goals (from requirements)

1. **MedGemma via Ollama is the default engine for everything**; a cloud model is the
   fallback and the option for users running online with no local model.
2. **Any provider, any base URL, any API key** — including arbitrary OpenAI-compatible
   endpoints and local Ollama models. Backed by **LiteLLM**.
3. **Per-role / per-agent model choice** — the user can point chat, clinical, literature,
   safety, critic, synthesizer, emergency, and the med-panel each at any profile.
4. **Hardcode OR ask** — if a key/URL is hardcoded (code or `.env`), use it silently; if
   not, the API signals `needs_key` and the UI prompts the user for it. Every profile's
   key can be hardcoded *separately*.
5. **Observability** — count every call, per agent / provider / model, with full metadata
   (tokens, latency, cost, debate round, success/error). In-memory + SQLite, plus optional
   Langfuse/LangSmith export.
6. **Debate-round controls** — increase/decrease rounds from settings and per request.
7. **Reliable and fast** — one code path, real fallbacks, parallel where safe.
8. **Polished/official presentation** — do not surface "Groq" everywhere; show the
   configured model name generically. Provider identity lives in advanced settings only.

---

## 1. Core concepts

### 1.1 Connection Profile
A named, reusable connection to one model on one provider.

```jsonc
{
  "id": "medgemma-local",
  "label": "MedGemma (Local)",         // shown in UI, de-branded
  "provider": "ollama",                 // ollama | openai | groq | azure | anthropic | openai_compatible
  "model": "medgemma",                  // model name as the provider expects it
  "base_url": "http://localhost:11434", // null = provider default
  "api_key_ref": null,                  // logical name of the secret (see §3); null if none needed
  "params": { "temperature": 0.2, "max_tokens": 4096, "json_mode": true }
}
```

### 1.2 Role → routing table
Each **role** (one per agent + chat) maps to a primary profile and an ordered fallback list.

```jsonc
"roles": {
  "default":     { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "chat":        { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "clinical":    { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "literature":  { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "safety":      { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "critic":      { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "synthesizer": { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "emergency":   { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] },
  "med_panel":   { "primary": "medgemma-local", "fallbacks": ["cloud-fast"] }
}
```

A role with no explicit entry inherits `default`. This is the "choose which model, where"
grid — the user can set `critic → cloud-fast` and leave the rest on MedGemma.

### 1.3 Full config file — `config/models.json`
```jsonc
{
  "version": 1,
  "profiles": { /* map of id -> Connection Profile */ },
  "roles":    { /* map of role -> {primary, fallbacks[]} */ },
  "debate":   { "max_rounds": 3, "min_rounds": 1, "consensus_required": true },
  "observability": { "sqlite": true, "langfuse": false, "langsmith": false }
}
```
This file is **read/written by the Settings UI**. It ships with a sensible default
(everything → MedGemma, fallback → cloud). It is safe to commit **without secrets**
(keys live elsewhere — §3).

---

## 2. LiteLLM integration

Add `litellm` to `requirements.txt`. All model calls go through one async function.

**Provider → LiteLLM model string / call mapping:**

| provider            | litellm `model`          | extra call args                       |
|---------------------|--------------------------|---------------------------------------|
| `ollama`            | `ollama/<model>`         | `api_base=base_url`                    |
| `openai`            | `<model>`                | `api_key`                              |
| `groq`              | `groq/<model>`           | `api_key`                             |
| `azure`             | `azure/<deployment>`     | `api_base`, `api_key`, `api_version`  |
| `anthropic`         | `anthropic/<model>`      | `api_key`                             |
| `openai_compatible` | `openai/<model>`         | `api_base=base_url`, `api_key`        |

`openai_compatible` covers **any** endpoint that speaks the OpenAI wire format (vLLM,
LM Studio, OpenRouter, Together, a self-hosted gateway, etc.) — the user just sets
`base_url` + key.

**Unified call (new `llm_client.py`):**
```python
async def llm_call(role: str, system_prompt: str, user_message: str,
                   json_mode: bool | None = None, temperature=None,
                   max_tokens=None, request_id=None, debate_round=None) -> LLMResult:
    plan = resolve_role(role)          # -> [primary_profile, *fallback_profiles]
    last_err = None
    for profile in plan:
        key = resolve_secret(profile)  # §3 — may raise NeedsKey
        try:
            t0 = time.monotonic()
            resp = await litellm.acompletion(**build_litellm_args(profile, ...))
            record_trace(success=True, profile=profile, role=role, resp=resp, ...)  # §4
            return parse(resp)
        except NeedsKey as e:
            record_trace(success=False, error="needs_key", ...);  raise
        except Exception as e:
            last_err = e
            record_trace(success=False, profile=profile, role=role, error=e, ...)
            continue                    # try next fallback
    raise AllProvidersFailed(role, last_err)
```

- `json_mode`/`temperature`/`max_tokens` default from the profile's `params`, overridable
  per call.
- Groq free-tier truncation/retry logic (currently in `_groq_call`) is **preserved** but
  becomes a per-profile concern keyed on `provider == "groq"`, not the whole app.
- **Chat now uses this too** (role `chat`), so MedGemma/Ollama works for chat — fixing
  the current gap where `/api/chat` bypasses Ollama entirely.

---

## 3. Secrets: hardcode-OR-ask

Each profile references a secret by logical name (`api_key_ref`, e.g. `"GROQ_API_KEY"`,
`"OPENROUTER_KEY"`). Resolution order in `resolve_secret(profile)`:

1. **Hardcoded** — `config/secrets.local.py` (gitignored) `HARDCODED_KEYS` dict, then
   environment / `.env`. If present → use it, never ask.
2. **Runtime override** — value the user typed into the UI this session (in-memory only).
3. **Neither** → raise `NeedsKey(profile_id, api_key_ref)`. The endpoint returns HTTP 428
   with `{ "needs_key": true, "profile": "...", "key_ref": "..." }`; the UI opens a prompt,
   user submits, value is stored as a runtime override, request retried.

Profiles with `api_key_ref: null` (e.g. local Ollama) never ask.

**`config/secrets.local.py` (gitignored) — the hardcode file:**
```python
# Hardcode any key here to skip the UI prompt entirely.
HARDCODED_KEYS = {
    "GROQ_API_KEY": "gsk_...",
    "OPENAI_API_KEY": "",          # empty = not hardcoded, will be asked
    "OPENROUTER_KEY": "",
    # base URLs can also be hardcoded/overridden per profile if desired:
    # "OLLAMA_BASE_URL": "http://localhost:11434",
}
```
`.gitignore` gets `config/secrets.local.py`. `config/secrets.local.example.py` is committed
as a template. Setup instructions go in INSTALL.md (see §9).

---

## 4. Observability stack

### 4.1 Trace record (one per LLM attempt)
```python
{
  "id": uuid, "ts": iso8601, "request_id": str,   # groups all calls in one analysis
  "role": "critic", "profile": "cloud-fast",
  "provider": "groq", "model": "llama-3.3-70b-versatile",
  "base_url": "...", "debate_round": 2,
  "tokens_in": int, "tokens_out": int, "tokens_total": int,
  "latency_ms": int, "cost_usd": float|null,       # litellm.completion_cost when available
  "success": bool, "error": str|null, "fallback_index": int
}
```

### 4.2 Store
- **In-memory ring buffer** (last N, e.g. 5000) for live dashboard speed.
- **SQLite** (`data/observability.db`, table `traces`) for durable history — survives restart.
- Writes are non-blocking (append to buffer + queue SQLite insert); observability must
  never break a clinical call.
- **Optional export**: if `observability.langfuse`/`langsmith` enabled and keys present,
  mirror each trace to that platform. Off by default.

### 4.3 Endpoints
| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/observability/summary` | totals: calls, per-agent, per-provider, per-model, tokens, avg latency, error rate, est. cost |
| GET | `/api/observability/traces?limit=&role=&request_id=` | recent raw traces (filterable) |
| GET | `/api/observability/run/{request_id}` | every call for one analysis (debate audit) |
| DELETE | `/api/observability/traces` | clear history |

### 4.4 Dashboard (new frontend tab "Observability")
- Top stat tiles: total calls, active/last run, avg latency, error rate, total tokens, est cost.
- Per-agent table (calls, avg latency, tokens, errors) and per-model breakdown.
- Live "current run" timeline: each agent call with round, model, latency, success — the
  "how many calls, how many agents, metadata behind everything" view.
- Follows the `dataviz` skill palette; theme-aware.

---

## 5. Debate-round controls

- `config/models.json → debate.{max_rounds,min_rounds,consensus_required}` is the persisted
  default, editable in Settings.
- `AnalysisRequest` gains an optional `max_debate_rounds` for per-request override.
- Orchestrator/debate engine read the effective value (request → runtime → config → default)
  instead of the cached `settings.max_debate_rounds`.
- The fragile `_using_groq()` parallel/sequential heuristic is replaced: sequential spacing
  is applied only when the **resolved profile's provider is a rate-limited cloud tier**
  (flag on the profile: `"serialize": true`), not inferred from "no OpenAI key".

---

## 6. De-branding

- Remove hardcoded "OpenAI with Groq fallback", "Groq", "Llama 3.3 70B — free via Groq"
  strings from user-facing copy (chat subtitle line ~1148, `ApiKeyModal` labels,
  `providerLabel` maps).
- User-facing surfaces show the **profile label + model** generically, e.g.
  "Clinical Engine · MedGemma" or just the model name. Health/degraded state shown as a
  neutral dot, not a provider name.
- Raw provider names appear only inside **advanced Settings** (where you configure profiles).

---

## 7. Files — create / modify

**New**
- `backend/llm/registry.py` — load/validate/save `models.json`, resolve roles, CRUD profiles.
- `backend/llm/secrets.py` — `resolve_secret`, `NeedsKey`, hardcoded/runtime/ask logic.
- `backend/llm/router.py` — `build_litellm_args`, fallback loop (or fold into `llm_client`).
- `backend/observability/store.py` — ring buffer + SQLite + optional external export.
- `config/models.json` — default config (committed).
- `config/secrets.local.example.py` — template (committed); `secrets.local.py` gitignored.

**Modified**
- `backend/agents/llm_client.py` — rewrite `llm_call` to be role-based + LiteLLM; keep
  `load_prompt`. Delete `_openai_call/_ollama_call/_groq_call` hand-rolled paths (LiteLLM
  handles them); keep Groq truncation as a per-profile helper.
- All agents (`clinical, literature, safety, critic`), `emergency.py`, `synthesizer.py`,
  `med_errors.py` — pass a `role=` instead of `model=settings.openai_fast_model`. Small,
  mechanical change per file.
- `backend/main.py` — `/api/chat` routed through `llm_call(role="chat")` (async, no sync
  clients, Ollama-capable); rewrite `/api/config-status`; replace `/api/set-api-key` with
  richer config endpoints (below); unify `/ws/analyze` to run the real multi-round debate.
- `backend/config.py` — keep for app settings; model routing moves to `registry.py`.
  Add `min_rounds`, drop reliance on lru_cache for model fields.
- `backend/observability/tracing.py` — becomes the optional Langfuse/LangSmith exporter
  used by `store.py`.
- `frontend/index.html` — new Settings (profiles + role grid + debate slider + connection
  test), new Observability tab, de-branded copy, `needs_key` prompt flow.
- `requirements.txt` — add `litellm`; keep `langsmith`, add `langfuse` (optional).
- `.env.example`, `.gitignore`, `INSTALL.md`, `ARCHITECTURE.md` — update.

**New/changed config endpoints (replacing `/api/set-api-key`):**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/config/models` | full routing config (secrets redacted) |
| PUT | `/api/config/models` | save edited config to `models.json` |
| POST | `/api/config/profiles` / PUT / DELETE | CRUD a profile |
| PUT | `/api/config/roles/{role}` | set a role's primary/fallbacks |
| POST | `/api/config/secret` | set a runtime key (memory only) `{key_ref, value}` |
| POST | `/api/config/test` | connection test for a profile (ping Ollama `/api/tags`, `/v1/models`, or a 1-token completion) |
| GET | `/api/config/discover?profile=` | list available models on that endpoint |

---

## 8. Frontend Settings UX

1. **Engines** tab — cards for each profile: label, provider, model (dropdown from discovery
   or free text), base URL, key field (shows "hardcoded ✓" or an input), **Test** button.
2. **Routing** tab — a grid: rows = agents/chat, columns = Primary / Fallbacks, each a
   profile dropdown. "Set all to MedGemma" / "Set all to Cloud" quick actions.
3. **Debate** — slider min/max rounds + consensus toggle.
4. **`needs_key` prompt** — when any call returns 428, a modal asks only for that one key,
   stores it as a runtime override, retries.

---

## 9. Setup instructions to ship (INSTALL.md additions)

- **Run MedGemma locally:** install Ollama → `ollama pull medgemma` (or the exact tag) →
  it's the default profile, no key needed.
- **Add a cloud fallback:** either (a) hardcode — copy `config/secrets.local.example.py`
  to `config/secrets.local.py`, set the key; or (b) leave blank and enter it in the UI when
  prompted.
- **Use any custom endpoint:** in Settings → Engines → New profile → provider
  `openai_compatible`, set base URL + key. Works for OpenRouter, vLLM, LM Studio, gateways.
- **Point one agent at a different model:** Settings → Routing → change that row.

---

## 10. Phasing (for when we build)

- **Phase 1 — Model core:** registry + secrets + LiteLLM router + wire all agents & chat +
  config endpoints + minimal Settings UI. Everything defaults to MedGemma→cloud. *Ship & review.*
- **Phase 2 — Observability:** store + endpoints + dashboard tab. *Ship & review.*
- **Phase 3 — Controls & polish:** debate-round settings, de-branding, connection test +
  discovery, `needs_key` flow, unify WebSocket path, PHI-egress guard, trace export.

---

## 11. Risks / edge cases

- **LiteLLM Ollama JSON mode** — some local models ignore `response_format`; keep the
  existing "parse JSON, fall back to raw string" guard in every agent's `_parse_output`.
- **MedGemma output quality for strict JSON** — may need per-profile prompt nudges; the
  parse-guard prevents hard failures.
- **Secrets never logged** — redact keys in all trace/error output and API responses.
- **PHI to cloud** — the egress guard (Phase 3) warns before patient text hits a cloud
  profile; MedGemma-local is the privacy-safe default.
- **Back-compat** — keep `/api/set-api-key` as a thin alias mapping to `/api/config/secret`
  so nothing breaks mid-migration.
- **Observability must be fire-and-forget** — a store failure must never fail a clinical call.

---
*Plan authored: 2026-07-21. Implementation not started.*
