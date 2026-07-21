# ClinicalPilot — Installation Guide

Complete setup instructions for all platforms.

---

## Prerequisites

| Tool | Version | Required | Install |
|------|---------|----------|---------|
| Python | 3.10+ | Yes | https://python.org or `brew install python@3.12` |
| pip | Latest | Yes | Comes with Python |
| Git | 2.x+ | Yes | `brew install git` or https://git-scm.com |
| Node.js | 18+ | No | Only if you want to customize frontend build |
| Ollama | Latest | No | Only for local LLM (MedGemma) |
| Docker | 24+ | No | Only for container deployment |

---

## Quick Start (5 minutes)

### 1. Clone the Repository

```bash
git clone <your-repo-url> clinicalpilot
cd clinicalpilot
```

### 2. Create Python Virtual Environment

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure a model engine

**No API key is required to start.** ClinicalPilot defaults every agent and chat to
**MedGemma via local Ollama** (see [Local LLM Setup](#local-llm-setup-optional--medgemma-via-ollama)).

You have three ways to provide a model — pick any:
- **Local (recommended, no key):** install Ollama + pull MedGemma. Nothing else to configure.
- **Cloud, entered in the app:** just run it — when a call needs a cloud key, the UI prompts
  you for exactly that key (stored in memory for the session).
- **Cloud, hardcoded:** `cp .env.example .env` and set e.g. `GROQ_API_KEY` / `OPENAI_API_KEY`,
  **or** hardcode in `config/secrets.local.py` (see [Model Engines & Routing](#model-engines--routing-configurable)).

Everything about *which* engine each agent uses is configured live in the **Settings** tab or
in `config/models.json` — not in `.env`.

### 5. Run the Application

```bash
# Start the FastAPI backend (serves frontend too)
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser, then open **Settings** to configure engines and routing.

---

## Detailed Installation

### Python Dependencies Breakdown

```bash
# Core framework
pip install fastapi uvicorn[standard] python-multipart

# LLM & Agents (litellm = unified client for Ollama/OpenAI/Groq/Azure/Anthropic/any OpenAI-compatible endpoint)
pip install litellm openai groq langchain langchain-openai langchain-community

# Data models & validation
pip install pydantic pydantic-settings

# Vector DB (LanceDB)
pip install lancedb

# Embeddings
pip install sentence-transformers

# PDF / Document parsing
pip install unstructured[pdf] PyPDF2

# PHI Anonymization (Microsoft Presidio)
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_lg

# PubMed API
pip install biopython

# Observability
pip install langsmith

# HTTP client
pip install httpx aiohttp

# Utilities
pip install python-dotenv jinja2

# WebSocket support (included in uvicorn[standard])
# pip install websockets
```

Or just run:
```bash
pip install -r requirements.txt
```

### SpaCy Model (Required for Presidio)

```bash
# Recommended: install directly via pip (avoids spaCy 3.7.x download URL bug)
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl
```

Alternatively (if `spacy download` works on your system):
```bash
python -m spacy download en_core_web_lg
```

This is ~560MB. If you need a smaller model:
```bash
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
# Then set SPACY_MODEL=en_core_web_sm in .env
```

---

## API Keys Setup

> All LLM keys are **optional** — the app runs on local MedGemma with no key. Add a cloud key
> only if you want to route some/all agents to a cloud engine. Any key here can be entered in the
> **Settings** UI on demand instead of stored in `.env`. See
> [Model Engines & Routing](#model-engines--routing-configurable) for hardcode-vs-ask details.

### OpenAI (optional cloud engine)

1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Provide it either way:
   - **In the app:** Settings → Engines → *Cloud Quality* → paste the key, **or**
   - **Hardcoded:** add `OPENAI_API_KEY=sk-...` to `.env` or `config/secrets.local.py`

### NCBI / PubMed (Recommended)

1. Register at https://www.ncbi.nlm.nih.gov/account/
2. Go to Settings → API Key Management → Create API Key
3. Add to `.env`:
   ```
   NCBI_API_KEY=your-key-here
   NCBI_EMAIL=your-email@example.com
   ```

Without an API key, PubMed limits you to 3 requests/second (vs 10 with key).

### LangSmith (Optional — Observability)

1. Go to https://smith.langchain.com/
2. Sign up (free tier available)
3. Create an API key
4. Add to `.env`:
   ```
   LANGSMITH_API_KEY=lsv2_...
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_PROJECT=clinicalpilot
   ```

### FDA API (Optional)

1. Go to https://open.fda.gov/apis/authentication/
2. Request an API key (instant)
3. Add to `.env`:
   ```
   FDA_API_KEY=your-key-here
   ```

Works without a key but has lower rate limits.

### Groq (optional cloud engine — the default fallback)

1. Go to https://console.groq.com/keys
2. Create a free API key
3. Provide it either way:
   - **In the app:** Settings → Engines → *Cloud Fast* → paste the key, **or**
   - **Hardcoded:** add `GROQ_API_KEY=gsk_...` to `.env` or `config/secrets.local.py`

*Cloud Fast* is the default fallback engine for every role. If a call routes to it and no key is
available, the app returns a `needs_key` prompt (HTTP 428) so you can enter it — the rest of the
app keeps working. To change which model it uses, edit the engine in Settings.

---

## Data Downloads (Manual Steps)

### DrugBank Open Data

1. Go to https://go.drugbank.com/releases/latest#open-data
2. Create a free account
3. Download "DrugBank Vocabulary" CSV
4. Place in `data/drugbank/drugbank_vocabulary.csv`

**If you can't download DrugBank**, the system will still work — it will use FDA API and RxNorm for safety checks instead. DrugBank adds offline drug name resolution.

### Sample FHIR Data (For Testing)

The repo includes sample FHIR bundles in `data/sample_fhir/`. No download needed.

To add your own:
1. Export FHIR R4 Bundle JSON from any EHR
2. Place in `data/sample_fhir/`
3. Use the `/api/upload/fhir` endpoint

---

## Local LLM Setup (Optional — MedGemma via Ollama)

### Install Ollama

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows
# Download from https://ollama.ai/download
```

### Start Ollama Server

```bash
ollama serve
# Runs on http://localhost:11434 by default
```

### Pull MedGemma Model

```bash
# Pull whichever MedGemma tag your Ollama registry provides, e.g.:
ollama pull medgemma        # or medgemma:4b / medgemma:27b, etc.

# Verify what you have:
ollama list
```

> **Important:** the default engine's model name is `medgemma` (see `config/models.json`).
> If your pulled tag differs (e.g. `medgemma:27b`), set it to match in
> **Settings → Engines → MedGemma (Local) → Model** (or use the **discover** button to pick
> from installed models). No restart needed.

MedGemma via Ollama is the **default engine for every agent and chat** — no key required.
If Ollama is unreachable, each role automatically falls back to its configured cloud engine.

---

## Model Engines & Routing (configurable)

ClinicalPilot routes every model call through a **registry** you can edit live in the app
(**Settings** tab) or on disk (`config/models.json`). Backed by **LiteLLM**, it supports
Ollama, OpenAI, Groq, Azure, Anthropic, and **any OpenAI-compatible endpoint** (OpenRouter,
vLLM, LM Studio, a gateway) — any model, any base URL, any key.

### Concepts
- **Engine (profile)** — one model on one provider: `{provider, model, base_url, api_key_ref}`.
- **Role** — each agent + chat (`clinical, literature, safety, critic, synthesizer,
  emergency, med_panel, chat`) maps to a **primary engine + fallbacks**.
- Default: everything → **MedGemma (Local)**, fallback → a cloud engine.

### Configure in the UI
Open **Settings** (gear icon or the Settings view):
- **Engines** — add/edit engines, set model/base URL/key, **Test** the connection, **discover** installed models. Each engine has a per-engine **JSON**, **Max tok**, **Temp**, and **Serial** toggle.
- **Routing** — pick which engine each agent uses (e.g. run the critic on the cloud, everything else on MedGemma).
- **Debate** — increase/decrease max debate rounds.

### Reasoning models & the JSON toggle (important for MedGemma)
**MedGemma 1.5 is a reasoning model** — it emits a private chain-of-thought (wrapped in
`<unused94>…<unused95>` tokens) before its answer. Two things follow, both handled for you:

- The app **strips the thinking block** from every reply, so chat shows only the answer and
  agents still get clean JSON.
- Forcing a **JSON grammar** (`response_format`) on a reasoning model makes it stall or crawl.
  So the built-in **MedGemma (Local)** engine ships with **JSON grammar OFF** (`json_mode: false`):
  the model generates freely and the app parses the JSON out of its reply. Hosted engines
  (OpenAI/Groq) keep grammar ON.

If you add your own local/gateway engine and it hangs or dribbles output, open
**Settings → Engines → your engine → JSON** and switch it **off**. Replies are still parsed
either way — this only removes the grammar constraint that small local models struggle with.

> The JSON toggle controls the *grammar constraint only*. Agents always parse structured
> output regardless; turning JSON off never means "lose the structured result."

### Hardcode keys (so you're never prompted) — OR let the app ask
Resolution order for every key: **hardcoded → runtime (UI) → ask on demand**.

To hardcode:
```bash
cp config/secrets.local.example.py config/secrets.local.py
# then edit config/secrets.local.py:
#   HARDCODED_KEYS = {"GROQ_API_KEY": "gsk_...", "OPENAI_API_KEY": "sk-..."}
```
`config/secrets.local.py` is gitignored and never committed. Environment variables / `.env`
work the same way. If a key is **not** hardcoded, the app returns a prompt and you enter it
in the UI (stored in memory only, cleared on restart).

### Example: MedGemma everywhere, cloud only as fallback
1. Ollama running with `ollama pull medgemma` (default engine).
2. Settings → Engines → **Cloud Fast** → set the key (or hardcode `GROQ_API_KEY`).
3. Done — local-first, with an automatic cloud fallback when Ollama is down or you're online-only.

---

## LanceDB Initialization

LanceDB is serverless/embedded — no separate server needed.

```bash
# Auto-creates on first run. To manually initialize:
python -m backend.rag.lancedb_store --init
```

This creates the vector store at `data/lancedb/`.

To add custom medical documents to RAG:
```bash
# Place PDF/TXT files in data/rag_documents/
# Then run:
python -m backend.rag.lancedb_store --ingest data/rag_documents/
```

---

## Running the Application

### Development Mode

```bash
# With auto-reload
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Production Mode

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Docker (Optional)

```bash
docker-compose up --build
```

---

## Verification Checklist

After setup, verify everything works. Steps 2–4 need a **runnable engine** — either Ollama
serving your MedGemma tag, or a cloud key configured in Settings. Without one they return a
clean `{"needs_key": ...}` (HTTP 428), which itself confirms routing works.

```bash
# 1. Health check (shows the active default engine)
curl http://localhost:8000/api/health

# 2. Model config (engines + per-agent routing; secret VALUES are redacted)
curl http://localhost:8000/api/config/models

# 3. Test AI Chat (routed via the 'chat' role)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What are the red flags for chest pain?"}]}'

# 4. Test with sample case (full multi-agent debate → SOAP note)
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "45-year-old male presenting with acute chest pain radiating to left arm, diaphoresis, and shortness of breath. History of hypertension and type 2 diabetes. Current medications: metformin 1000mg BID, lisinopril 20mg daily."}'

# 5. Observability metrics (populates after any call above)
curl http://localhost:8000/api/observability/summary

# 6. Check API docs / the app UI
open http://localhost:8000/docs
open http://localhost:8000/          # then: Settings tab + Observability tab
```

---

## Troubleshooting

### "No module named 'backend'"
Make sure you're running from the project root:
```bash
cd /path/to/clinicalpilot
python -m uvicorn backend.main:app --reload
```

### Presidio / SpaCy errors
```bash
pip install presidio-analyzer presidio-anonymizer --force-reinstall
# Use pip install directly (spaCy 3.7.x has a download URL bug):
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl
```

### macOS SSL Certificate Errors
If you see `CERTIFICATE_VERIFY_FAILED` or `SSL: CERTIFICATE_VERIFY_FAILED` errors:
```bash
# Option 1: Run the macOS certificate installer (recommended)
/Applications/Python\ 3.12/Install\ Certificates.command

# Option 2: The app handles this automatically via certifi
# (backend/main.py patches ssl to use certifi's cert bundle)
pip install certifi
```

### LanceDB import errors
```bash
pip install lancedb --upgrade
```

### "needs_key" / an API key prompt appears
A call routed to a cloud engine and no key was found. Either:
- enter the key when the app prompts (Settings → Engines), or
- hardcode it: `cp config/secrets.local.example.py config/secrets.local.py` and set the key, or
- switch that agent to a local engine in Settings → Routing.

### Analysis/chat hangs ~12s then prompts for a key
The engine is set to local MedGemma but Ollama isn't reachable, so it waits on the connection
before falling back. Start Ollama (`ollama serve`), or in Settings → Routing point the role at a
cloud engine (no local-connect wait).

### Chat shows `<unused94>thought…` / raw thinking tokens
That's a reasoning model's private chain-of-thought leaking through. The app strips it
automatically now — if you still see it, hard-refresh the page and make sure the backend was
restarted after updating. See
[Reasoning models & the JSON toggle](#reasoning-models--the-json-toggle-important-for-medgemma).

### The multi-agent pipeline spins forever / never produces output (local model)
Almost always a **reasoning model fighting a JSON grammar**. Fix: open **Settings → Engines →
your engine → JSON** and turn it **off** (the built-in MedGemma engine already ships this way).
Also consider lowering **Max tok** and, for a faster first run on a small local model,
**Settings → Debate → max rounds = 1–2**. Each debate round is several sequential model calls,
so on a 4B model high round counts are slow by nature.

### Port 8000 already in use
```bash
# Find and kill the process
lsof -ti:8000 | xargs kill -9
# Or use a different port
python -m uvicorn backend.main:app --reload --port 8001
```

### Ollama connection refused
```bash
# Make sure Ollama is running
ollama serve
# Check it's accessible
curl http://localhost:11434/api/tags
```

---

## Platform-Specific Notes

### macOS (Apple Silicon)
- All dependencies work natively on M1/M2/M3
- Ollama runs natively on Apple Silicon (Metal acceleration)
- SpaCy large model may take a few minutes to download
- **SSL may fail** — the app auto-patches SSL using `certifi`, but you can also run `/Applications/Python\ 3.12/Install\ Certificates.command`

### macOS (Intel)
- Same as above, Ollama uses CPU only
- Same SSL note as Apple Silicon

### Linux (Ubuntu/Debian)
```bash
# You may need system packages for PDF parsing
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr libmagic1
```

### Windows
```bash
# Use PowerShell or WSL2
# For Presidio on Windows, you may need Visual C++ Build Tools
# Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

---

## Updating

```bash
git pull
pip install -r requirements.txt --upgrade
# Restart the server
```

---

*Last updated: 2026-07-22*
