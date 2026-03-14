# ClinicalPilot

**Multi-agent clinical decision support. Debate-driven reasoning. Real SOAP notes.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)


---

## Why this exists

Most clinical AI tools are a single LLM call with a long prompt. That works for demos, not for patients.

ClinicalPilot runs **three specialized agents** — Clinical, Literature, Safety — through a **multi-round debate** with an adversarial Critic. They argue. They cite evidence. They disagree. After 2-3 rounds, a Synthesizer merges their output into a structured SOAP note, and a Medical Error Prevention Panel runs in parallel catching drug interactions, dosing issues, and contraindications.

The result: fewer hallucinations, more differential diagnoses, actual PubMed citations, and safety alerts that a single model would miss.

---

## What it actually does

- **Multi-agent debate** — 3 specialist agents + Critic, 2-3 adversarial rounds, consensus-or-flag-for-human-review
- **Emergency triage** — Bypasses the debate entirely, ESI scoring in <5 seconds, immediate action cards
- **Medical error prevention** — Drug-drug interactions, drug-disease contraindications, renal/hepatic dosing alerts, pregnancy/pediatric/elderly flags (RxNorm + DrugBank with optional openFDA lookups)
- **FHIR R4 + EHR upload** — Drop in FHIR bundles, PDFs, CSVs, or just type free-text clinical notes
- **PHI anonymization** — Microsoft Presidio scrubs protected health information before anything hits an LLM
- **RAG pipeline** — LanceDB vector store for medical literature retrieval and PubMed E-utilities for live citations
- **AI Chat** — Conversational assistant with OpenAI-first and Groq fallback for quick clinical Q&A
- **Runtime provider settings** — Enter OpenAI/Groq API keys from the UI (in-memory, no file edits required)
- **Human-in-the-loop** — Doctor edits feed back into the debate engine for re-analysis
- **Medical image classifiers** — External Streamlit apps (launched in in-app iframes) for lung disease, chest X-ray, retinopathy, and skin cancer analysis
- **Observability** — LangSmith tracing on every agent call, token tracking, latency breakdown
- **Guardrails** — Pydantic schema validation, hallucinated medication cross-checks, differential completeness rules

---

## Quick start

```bash
git clone <repo-url> && cd clinicalpilot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add at least one key: OPENAI_API_KEY and/or GROQ_API_KEY
# You can also set keys at runtime from the frontend Settings modal

python -m uvicorn backend.main:app --reload --port 8000
# Open http://localhost:8000
```

That's it. No npm, no webpack, no Docker required. The frontend is a single HTML file served by FastAPI.

Note: analysis outputs are returned in API responses and are not persisted to a database by default.

Full setup guide with platform-specific notes, optional local LLM (MedGemma via Ollama), and data downloads → [INSTALL.md](INSTALL.md)

---

## Architecture

```
Input (FHIR / EHR / Text / Voice)
    ↓
Anonymizer (Presidio PHI scrubbing)
    ↓
Parsers → Unified PatientContext
    ↓
┌─────────────────────────────────────────┐
│  DEBATE ENGINE (2-3 rounds)             │
│                                         │
│  Clinical Agent ──┐                     │
│  Literature Agent ─┼──→ Critic ──→ loop │
│  Safety Agent ────┘                     │
└─────────────────────────────────────────┘
    ↓                          ↓ (parallel)
Synthesizer → Validator   Med Error Panel
    ↓
SOAP Note + Safety Alerts + Citations
```

Full system design and layer-by-layer architecture reference → [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Project structure

```
clinicalpilot/
├── backend/
│   ├── main.py                 # FastAPI app — all endpoints + provider-aware chat
│   ├── config.py               # pydantic-settings config
│   ├── models/                 # Pydantic schemas (patient, SOAP, agents, safety)
│   ├── input_layer/            # Anonymizer, FHIR/EHR/text parsers
│   ├── agents/                 # Orchestrator, Clinical, Literature, Safety, Critic
│   │   └── prompts/            # System prompts (few-shot CoT)
│   ├── debate/                 # Multi-round debate engine
│   ├── validation/             # Synthesizer + output validator
│   ├── emergency/              # Emergency fast-path triage
│   ├── safety_panel/           # Drug interactions, dosing alerts
│   ├── external/               # PubMed, DrugBank, RxNorm, openFDA APIs
│   ├── rag/                    # LanceDB vector store + embeddings
│   ├── observability/          # LangSmith tracing
│   └── guardrails/             # Hallucination checks, schema validation
├── frontend/
│   └── index.html              # Full SPA — React 18 + Babel CDN (~1100 lines)
├── data/
│   ├── sample_fhir/            # Test FHIR R4 bundles (STEMI, Stroke, PE)
│   ├── sample_ehr/             # Test CSV patient data
│   ├── drugbank/               # DrugBank open CSV data
│   ├── few_shot_examples/      # Few-shot clinical examples
│   └── lancedb/                # Vector store (auto-created)
├── Flowcharts/                 # Interactive architecture diagrams (HTML)
├── ARCHITECTURE.md
├── INSTALL.md
├── _smoke_test.sh              # End-to-end smoke tests
├── requirements.txt
└── .env.example
```

---

## API

| Method | Path | What it does |
|--------|------|--------------|
| `POST` | `/api/analyze` | Full multi-agent debate pipeline → SOAP note |
| `POST` | `/api/emergency` | Emergency triage, ESI scoring (<5s) |
| `GET` | `/api/config-status` | Returns configured providers and active provider |
| `POST` | `/api/set-api-key` | Set OpenAI/Groq API key at runtime (memory only) |
| `POST` | `/api/chat` | AI chat via OpenAI-first with Groq fallback |
| `POST` | `/api/upload/fhir` | Upload FHIR R4 bundle JSON |
| `POST` | `/api/upload/ehr` | Upload PDF/CSV EHR documents |
| `POST` | `/api/human-feedback` | Doctor edits → triggers re-analysis |
| `GET` | `/api/safety-check` | Drug interaction lookup (RxNorm + DrugBank) |
| `GET` | `/api/classifiers` | List available imaging classifier apps |
| `GET` | `/api/health` | Health check |
| `WS` | `/ws/analyze` | WebSocket streaming — real-time pipeline visualization |

---

## Operational snapshot

1. Configure at least one provider key (`OPENAI_API_KEY` and/or `GROQ_API_KEY`) or enable local Ollama.
2. Run `python -m uvicorn backend.main:app --reload --port 8000`.
3. Use Analysis for full multi-agent SOAP generation and Emergency for fast triage.
4. Set or switch keys at runtime from Settings (`/api/config-status`, `/api/set-api-key`).
5. Use `_smoke_test.sh` for quick end-to-end verification.

---

## Frontend

Zero-build React 18 SPA — no Node.js, no bundler. Served straight from FastAPI.

| View | What's in it |
|------|-------------|
| **Analysis** | Free-text or voice input, FHIR/CSV upload with sample data buttons, real-time WebSocket pipeline stages, full SOAP report with PDF export, doctor feedback loop |
| **Emergency** | Fast-path triage, ESI scoring, red flag identification, immediate action cards |
| **Tools** | Drug interaction checker (multi-drug, RxNorm-backed), BMI calculator, MAP calculator, clinical reference tables |
| **Imaging AI** | External Streamlit classifier apps rendered in iframes — lung disease, chest X-ray, diabetic retinopathy, skin cancer |
| **Architecture** | Live Mermaid.js diagrams — system flow and data pipeline |
| **AI Chat** | Conversational clinical Q&A with OpenAI-first and Groq fallback, multi-turn conversation history, provider metadata |

---

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.10+, FastAPI, uvicorn, async everywhere |
| Agents | Local Ollama (optional) → OpenAI → Groq fallback |
| AI Chat | OpenAI-first chat with Groq fallback |
| Vector DB | LanceDB (embedded, serverless) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| PHI Safety | Microsoft Presidio + spaCy (en_core_web_lg) |
| Drug Data | PubMed (BioPython Entrez), DrugBank, RxNorm, optional openFDA lookups |
| Frontend | React 18 CDN + Tailwind CSS + Babel (zero build step) |
| Observability | LangSmith tracing + token/latency tracking |
| Validation | Pydantic v2 schemas + custom guardrail rules |

---

## Smoke tests

```bash
bash _smoke_test.sh
```

Validates: health check, full analysis pipeline (~100s with 14 LLM calls), emergency mode (~3s), drug safety checks, classifier listing. Results are logged with timing.

Example latest run: all checks passed (health, full analysis, emergency mode, safety check, classifiers).

---
