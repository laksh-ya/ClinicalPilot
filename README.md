# 🏥 ClinicalPilot

**Multi-Agent Clinical Decision Support System with Debate-Driven Reasoning**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is ClinicalPilot?

ClinicalPilot is an AI-powered clinical decision support system that uses **multiple specialized agents** in a structured **debate framework** to generate evidence-based SOAP notes. Unlike single-LLM approaches, ClinicalPilot forces adversarial review and multi-round deliberation to reduce hallucination and improve diagnostic accuracy.

### Key Features

- **Multi-Agent Debate Architecture** — Clinical, Literature, and Safety agents deliberate across 2-3 rounds with a Critic adversary
- **Emergency Mode** — Fast-path triage with ESI scoring in <5 seconds
- **Medical Error Prevention Panel** — Drug interactions, contraindications, dosing alerts, population flags
- **FHIR R4 Compatible** — Upload FHIR bundles, EHR PDFs, or free-text clinical notes
- **PHI Anonymization** — Microsoft Presidio integration with HIPAA-compliant de-identification
- **RAG Pipeline** — LanceDB vector store + PubMed + DrugBank + RxNorm + openFDA
- **Human-in-the-Loop** — Doctor edits trigger re-analysis through the debate engine
- **Medical Image Classifiers** — Embedded Streamlit apps for lung, chest, retina, and skin analysis
- **Observable** — LangSmith tracing, guardrail checks, confidence scoring

## Quick Start

```bash
# 1. Clone & setup
git clone <repo-url> && cd clinicalpilot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env → add your OPENAI_API_KEY

# 3. Run
python -m uvicorn backend.main:app --reload --port 8000

# 4. Open
# → http://localhost:8000
```

## Architecture

```
Input Layer → Processing → Multi-Agent (Clinical + Literature + Safety)
                              ↓
                        Debate Engine (2-3 rounds with Critic)
                              ↓
                        Synthesizer → Validator → SOAP Note
                              ↓
                     Medical Error Prevention Panel
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete system design and progress tracker.

See [INSTALL.md](INSTALL.md) for detailed installation instructions across all platforms.

## Project Structure

```
clinicalpilot/
├── backend/
│   ├── main.py              # FastAPI app + all endpoints
│   ├── config.py             # Settings (pydantic-settings)
│   ├── models/               # Pydantic data models
│   ├── input_layer/          # Anonymizer, FHIR/EHR/text parsers
│   ├── agents/               # LLM client + Clinical/Literature/Safety/Critic agents
│   │   └── prompts/          # System prompts (few-shot, CoT)
│   ├── debate/               # Multi-round debate engine
│   ├── validation/           # Synthesizer + output validator
│   ├── emergency/            # Emergency fast-path triage
│   ├── safety_panel/         # Medical error prevention
│   ├── external/             # PubMed, DrugBank, RxNorm, FDA APIs
│   ├── rag/                  # LanceDB + sentence-transformers
│   ├── observability/        # LangSmith tracing
│   └── guardrails/           # Hallucination + completeness checks
├── frontend/
│   ├── index.html            # SPA entry point
│   ├── styles.css            # Custom styles (+ Tailwind CDN)
│   └── app.js                # Full frontend logic
├── data/
│   ├── sample_fhir/          # Test FHIR R4 bundles
│   └── sample_ehr/           # Test CSV data
├── ARCHITECTURE.md            # System design reference
├── INSTALL.md                 # Installation guide
├── requirements.txt
├── .env.example
└── .gitignore
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/analyze` | Full analysis pipeline |
| `POST` | `/api/emergency` | Emergency triage (<5s) |
| `POST` | `/api/upload/fhir` | Upload FHIR R4 bundle |
| `POST` | `/api/upload/ehr` | Upload PDF/CSV EHR |
| `POST` | `/api/human-feedback` | Doctor feedback → re-analysis |
| `GET` | `/api/safety-check` | Drug interaction check |
| `GET` | `/api/classifiers` | List classifier apps |
| `WS` | `/ws/analyze` | WebSocket streaming analysis |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.10+, FastAPI, uvicorn |
| LLM | GPT-4o / GPT-4o-mini (+ Ollama fallback) |
| Vector DB | LanceDB (serverless, embedded) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| PHI Safety | Microsoft Presidio + spaCy |
| External Data | PubMed, DrugBank, RxNorm, openFDA |
| Frontend | Vanilla JS + Tailwind CSS (no build step) |
| Observability | LangSmith |

## License

MIT

---

## Smoke Test

A built-in smoke test script validates all endpoints:

```bash
bash _smoke_test.sh
```

Tests: health check, full analysis pipeline (with timing), emergency mode, drug safety check, and classifier listing. See [ARCHITECTURE.md](ARCHITECTURE.md) for latest test results.
