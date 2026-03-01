# ClinicalPilot — Architecture Reference & Progress Tracker

> **Purpose**: This file is the single source of truth for the entire ClinicalPilot system.
> Any IDE agent (Copilot, Cursor, Windsurf, Cline, etc.) should read this file to understand the project layout, status, and remaining work.

---

## Project Structure

```
clinicalpilot/
├── ARCHITECTURE.md          ← THIS FILE (reference for all agents/IDEs)
├── INSTALL.md               ← Full installation instructions
├── README.md                ← Public-facing README
├── .env.example             ← Template for environment variables
├── .env                     ← Local secrets (NEVER commit)
├── .gitignore
├── requirements.txt         ← Python dependencies
├── pyproject.toml           ← Project metadata
│
├── Flowcharts/              ← Visual architecture diagrams (HTML)
│
├── backend/                 ← FastAPI Python backend
│   ├── main.py              ← FastAPI app + all endpoints + Groq chat
│   ├── config.py            ← Settings / env loading (incl. Groq config)
│   │
│   ├── models/              ← Pydantic data models
│   │   ├── __init__.py
│   │   ├── patient.py       ← PatientContext, UnifiedSchema
│   │   ├── soap.py          ← SOAP note models
│   │   ├── agents.py        ← Agent input/output models
│   │   └── safety.py        ← Drug interaction / safety models
│   │
│   ├── input_layer/         ← Input Gateway + Anonymizer
│   │   ├── __init__.py
│   │   ├── anonymizer.py    ← Microsoft Presidio PHI scrubbing
│   │   ├── fhir_parser.py   ← FHIR JSON → PatientContext
│   │   ├── ehr_parser.py    ← PDF/CSV upload → PatientContext
│   │   └── text_parser.py   ← Free text / voice → PatientContext
│   │
│   ├── agents/              ← Multi-Agent Layer
│   │   ├── __init__.py
│   │   ├── orchestrator.py  ← Main controller / router
│   │   ├── clinical.py      ← Clinical reasoning agent
│   │   ├── literature.py    ← PubMed / RAG literature agent
│   │   ├── safety.py        ← Drug-drug / contraindication agent
│   │   ├── critic.py        ← Debate critic agent
│   │   └── prompts/         ← System prompts for each agent
│   │       ├── clinical_system.txt
│   │       ├── literature_system.txt
│   │       ├── safety_system.txt
│   │       ├── critic_system.txt
│   │       ├── emergency_system.txt
│   │       └── synthesizer_system.txt
│   │
│   ├── debate/              ← Debate Layer (multi-round)
│   │   ├── __init__.py
│   │   └── debate_engine.py ← Debate orchestration (2-3 rounds)
│   │
│   ├── validation/          ← Validator + Output Formatting
│   │   ├── __init__.py
│   │   ├── validator.py     ← Output completeness, safety clearance
│   │   └── synthesizer.py   ← Final SOAP synthesis
│   │
│   ├── emergency/           ← Emergency Mode (fast path)
│   │   ├── __init__.py
│   │   └── emergency.py     ← Bypasses debate, <5s response
│   │
│   ├── safety_panel/        ← Medical Error Prevention Panel
│   │   ├── __init__.py
│   │   └── med_errors.py    ← Drug interactions, dosing alerts
│   │
│   ├── rag/                 ← RAG / Vector DB layer
│   │   ├── __init__.py
│   │   ├── lancedb_store.py ← LanceDB vector store
│   │   └── embeddings.py    ← Embedding utilities
│   │
│   ├── external/            ← External API integrations
│   │   ├── __init__.py
│   │   ├── pubmed.py        ← PubMed E-utilities (BioPython)
│   │   ├── drugbank.py      ← DrugBank open data lookups
│   │   ├── rxnorm.py        ← RxNorm API
│   │   └── fda.py           ← FDA openFDA API
│   │
│   ├── observability/       ← Tracing & monitoring
│   │   ├── __init__.py
│   │   └── tracing.py       ← LangSmith / Langfuse integration
│   │
│   └── guardrails/          ← Output validation rules
│       ├── __init__.py
│       └── rules.py         ← Pydantic validators, hallucination checks
│
├── frontend/                ← React 18 CDN frontend (zero build step)
│   ├── index.html           ← Complete SPA (~1100 lines: React 18 + Babel CDN + Tailwind)
│   ├── app.js               ← Backward-compat stub
│   └── styles.css           ← Backward-compat stub
│
└── data/                    ← Local data files
    ├── drugbank/            ← DrugBank open CSV data
    ├── few_shot_examples/   ← Few-shot clinical examples
    └── sample_fhir/         ← Sample FHIR bundles for testing
```

---

## Architecture Layers

### Layer 1: Input Gateway
- **FHIR API** (HL7 FHIR R4 JSON) → flattened to text chunks
- **EHR Upload** (PDF/CSV) → parsed via Unstructured.io / PyPDF2
- **Free Text / Voice** → direct text, future: Whisper STT
- **Anonymizer** → Microsoft Presidio (PHI scrubbing, FHIR-aware)

### Layer 2: Processing (Parsers → Unified Schema)
- FHIR Parser: Extracts Patient, Condition, Observation, MedicationRequest
- EHR Parser: PDF text extraction + chunking
- Text Parser: Direct prompt normalization
- All output → `PatientContext` (Pydantic model)

### Layer 3: Agent Layer
| Agent | Model | Tools | Output |
|-------|-------|-------|--------|
| Clinical | GPT-4o / MedGemma-2-9b | PatientContext + few-shot CoT | Differential dx, risk scores, SOAP draft |
| Literature | GPT-4o-mini | PubMed (BioPython Entrez — **parallel queries**), Europe PMC, RAG (LanceDB) | Evidence snippets, confidence, contradictions |
| Safety | GPT-4o / rule-based | DrugBank CSV, RxNorm (**parallel lookups**), FDA API (**parallel lookups**) | Structured warnings with severity |

### Groq AI Chat (Standalone)
- Endpoint: `POST /api/chat`
- Model: Llama 3.3 70B Versatile via Groq SDK
- Purpose: Fast conversational clinical Q&A — sub-second responses, no agent/debate overhead
- Maintains full conversation history (multi-turn)
- Uses a dedicated clinical system prompt (evidence-based, structured formatting, safety-first)
- Future: Will connect to LanceDB RAG for grounded answers

### Layer 4: Debate Layer
- **Per Round**: Clinical agent → (Literature + Safety in **parallel**) → Critic
- **Rounds 1-3**: Each round builds on critic feedback; if no consensus after 3 rounds → flag for human review
- **Med Error Panel**: Runs in **parallel** alongside the debate pipeline via `asyncio.gather`
- Implementation: async Python with structured state

### Layer 5: Validation & Output
- Validator checks completeness, format, safety clearance
- Final Synthesizer produces SOAP note
- Human-in-the-loop: doctor edits → optional re-debate (max 1 iteration)

### Layer 6: Observability
- LangSmith (or Langfuse) for tracing every agent call
- Token usage, latency breakdown, debate visualization

### Layer 7: Guardrails
- Pydantic schema validation for SOAP output
- No hallucinated medications check (cross-ref DrugBank)
- Differential must have ≥2 options
- Safety flags must be explicit
- MUC confidence thresholds

### Emergency Mode
- Bypasses debate layer entirely
- Clinical + Safety agents run in parallel only
- Response target: <5 seconds
- Output: top 3 differentials, red flags, call-to-action
- ESI scoring for triage

### Medical Error Prevention Panel
- Runs as sidebar on every case
- Drug-drug interactions (severity tiers)
- Drug-disease contraindications
- Dosing alerts (renal/hepatic)
- Population flags (pregnancy, pediatric, elderly)

### Classifier Kit (External Streamlit Apps)
- Lung Disease: https://lung-disease-classification.streamlit.app/
- Chest Disease: http://caryaai.streamlit.app/
- AI Retina Analyser: https://retinopathy-detection.streamlit.app/
- Skin Cancer: https://skincancer-detection.streamlit.app/
- Embedded via iframe or linked with redirect fallback

---

## Progress Tracker

### ✅ Completed
- [x] Project structure created
- [x] ARCHITECTURE.md (this file)
- [x] INSTALL.md
- [x] Pydantic models (patient, SOAP, agents, safety)
- [x] Input Layer (anonymizer, FHIR parser, EHR parser, text parser)
- [x] Agent Layer (clinical, literature, safety agents)
- [x] Debate Layer (debate engine + critic agent)
- [x] Validation & Output Layer (validator + synthesizer)
- [x] Emergency Mode
- [x] Medical Error Prevention Panel
- [x] RAG Layer (LanceDB store + embeddings)
- [x] External APIs (PubMed, DrugBank, RxNorm, FDA)
- [x] Observability (tracing setup)
- [x] Guardrails (output validation rules)
- [x] FastAPI backend (main.py + all routes)
- [x] Frontend UI (full SPA)
- [x] Classifier Kit integration
- [x] Agent system prompts
- [x] Configuration & env template
- [x] requirements.txt
- [x] .gitignore
- [x] Sample data files
- [x] Groq-powered AI Chat (direct LLM, no agents — Llama 3.3 70B via Groq SDK)
- [x] `/api/chat` endpoint with conversation history support
- [x] Frontend ChatView rewired to Groq (sub-second responses)

### ✅ Bug Fixes & Optimizations (Post-Build)

#### Frontend (app.js)
- [x] **WebSocket handler crash** — `handleWSMessage` read `msg.message` (undefined); backend sends `msg.stage`/`msg.detail`. Silent TypeError swallowed ALL WS messages, causing `runAnalysis()` to hang forever. Fixed to read correct fields + added `agent_result` event handling.
- [x] **WS onclose never resolved** — WebSocket `onclose` was empty, so the analysis promise never resolved. Fixed to call `resolve(false)` on close.
- [x] **WS complete handler wrong fields** — `complete` event read `msg.data` but backend sends `msg.soap`/`msg.debate` at top level. Fixed.
- [x] **Differentials NaN%** — `d.confidence` is a string ("high"/"medium"/"low"), not a number. `Math.round("high" * 100)` → NaN. Fixed with string→percentage mapping.
- [x] **Safety panel empty** — Frontend used `panel.interactions` but backend sends `panel.drug_interactions`. All field names corrected.
- [x] **Emergency mode empty** — API returns `{emergency: {...}}` but frontend read `data.esi_score` directly. Fixed to unwrap `data.emergency`.
- [x] **Confidence badge wrong field** — Read `soap.confidence` but model has `soap.uncertainty`. Fixed.
- [x] **Metadata wrong fields** — Read non-existent response fields. Corrected to `debate.round_number`, `debate.final_consensus`, `soap.model_used`, `soap.latency_ms`.
- [x] **renderResults null guard** — Added `if (!data) return` to prevent crash on empty responses.

#### Backend — Performance (Parallelization)
- [x] **PubMed searches now parallel** — 3 queries run via `asyncio.gather` instead of sequential loop (~3× faster).
- [x] **FDA lookups now parallel** — Up to 5 drug lookups via `asyncio.gather` instead of sequential loop.
- [x] **RxNorm lookups now parallel** — RxCUI resolution for multiple drugs via `asyncio.gather`.
- [x] **Med Error Panel parallel** — Runs alongside the full debate pipeline via `asyncio.gather` instead of sequentially after it.

#### Backend — Anonymizer
- [x] **Presidio DATE_TIME corrupting medications** — Presidio matched dose strings like "20mEq" as dates → replaced with `[DATE]` → FDA searched for "Potassium [DATE]" (404 Not Found). Fixed by removing `DATE_TIME` from Presidio entity list and using targeted DOB regex post-processing instead.
- [x] **LOCATION false positives** — Added clinical term filtering to skip LOCATION entities that match common medical words (e.g., "HTN" recognized as a place name).

#### Backend — Other
- [x] **macOS SSL certificate fix** — `ssl._create_default_https_context` monkey-patch with certifi at startup. Fixes PubMed, spaCy, urllib3 SSL errors on macOS.
- [x] **spaCy en_core_web_lg** — Installed directly via pip (`en_core_web_lg==3.7.1`) to avoid broken download URL.
- [x] **Text parser med regex** — Fixed medication regex to handle varied dosage formats.

### 🔧 Manual Steps Required (MUST DO BY HAND)

#### API Keys & Secrets
1. **OpenAI API Key** — Get from https://platform.openai.com/api-keys
   - Set `OPENAI_API_KEY` in `.env`
2. **LangSmith API Key** (optional) — Get from https://smith.langchain.com/
   - Set `LANGSMITH_API_KEY` in `.env`
   - Set `LANGCHAIN_TRACING_V2=true`
3. **NCBI/PubMed API Key** — Register at https://www.ncbi.nlm.nih.gov/account/
   - Set `NCBI_API_KEY` and `NCBI_EMAIL` in `.env`

#### Data Downloads (Manual)
4. **DrugBank Open Data** — Download from https://go.drugbank.com/releases/latest#open-data
   - Place CSV files in `data/drugbank/`
   - File needed: `drugbank_vocabulary.csv` (drug names, interactions)
   - Also download "Drug Interactions" CSV if available on open tier
5. **RxNorm Data** (optional) — Download from https://www.nlm.nih.gov/research/umls/rxnorm/
   - Only needed if you want offline RxNorm lookups

#### Local LLM Setup (Optional — for MedGemma)
6. **Install Ollama** — https://ollama.ai
   ```bash
   # macOS
   brew install ollama
   # Then pull MedGemma
   ollama pull medgemma2:9b
   # Or for 27B (needs 32GB+ RAM)
   ollama pull medgemma2:27b
   ```
   - Set `USE_LOCAL_LLM=true` and `OLLAMA_BASE_URL=http://localhost:11434` in `.env`

#### LanceDB Initialization
7. **First run will auto-create** LanceDB tables in `data/lancedb/`
   - To pre-populate with medical literature, run:
   ```bash
   python -m backend.rag.lancedb_store --init
   ```

#### Groq API Key (Required for AI Chat)
8. **Groq API Key** — Get from https://console.groq.com/keys
   - Set `GROQ_API_KEY` in `.env`
   - Set `GROQ_MODEL` (optional, defaults to `llama-3.3-70b-versatile`)

#### Frontend Serving
9. The frontend is a static SPA — serve via FastAPI (auto-configured) or any static server
   - No build step required (vanilla JS)

#### Production Deployment (Future)
10. **Docker** — `docker-compose up` (compose file provided)
11. **HTTPS** — Required for production (use nginx reverse proxy)
12. **HIPAA Compliance** — Audit logging, encryption at rest, BAA with cloud provider

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT-4o / GPT-4o-mini |
| `OPENAI_MODEL` | No | Default: `gpt-4o` |
| `OPENAI_FAST_MODEL` | No | Default: `gpt-4o-mini` (for Literature agent) |
| `USE_LOCAL_LLM` | No | `true` to use Ollama/MedGemma instead of OpenAI |
| `OLLAMA_BASE_URL` | No | Default: `http://localhost:11434` |
| `OLLAMA_MODEL` | No | Default: `medgemma2:9b` |
| `NCBI_API_KEY` | No | PubMed E-utilities API key (higher rate limits) |
| `NCBI_EMAIL` | Yes* | Required by NCBI for E-utilities |
| `LANGSMITH_API_KEY` | No | LangSmith tracing key |
| `LANGCHAIN_TRACING_V2` | No | `true` to enable LangSmith tracing |
| `LANGCHAIN_PROJECT` | No | Default: `clinicalpilot` |
| `LANCEDB_PATH` | No | Default: `data/lancedb` |
| `FDA_API_KEY` | No | openFDA API key (optional, works without) |
| `LOG_LEVEL` | No | Default: `INFO` |
| `GROQ_API_KEY` | No* | Groq API key for AI Chat (required for `/api/chat`) |
| `GROQ_MODEL` | No | Default: `llama-3.3-70b-versatile` |
| `CORS_ORIGINS` | No | Default: `["*"]` |
| `EMERGENCY_TIMEOUT_SEC` | No | Default: `5` |
| `MAX_DEBATE_ROUNDS` | No | Default: `3` |

---

## Key Design Decisions

1. **LanceDB over ChromaDB/Pinecone**: Serverless, embedded, no infra cost. Perfect for hackathon.
2. **Async Python (asyncio)**: All agent calls are async for parallel execution.
3. **Pydantic everywhere**: Type safety, auto-validation, JSON schema generation.
4. **Static frontend**: React 18 + Babel CDN. No React build step, no npm. Fastest to iterate.
5. **FastAPI**: Auto-generates OpenAPI docs, async-native, WebSocket support.
6. **Debate fixed rounds (2-3)**: Deterministic, no infinite loops.
7. **Emergency mode bypass**: Separate fast path, no debate overhead.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze` | Full analysis pipeline (input → debate → SOAP) |
| POST | `/api/emergency` | Emergency mode (fast path, <5s) |
| POST | `/api/chat` | AI chat via Groq / Llama 3.3 70B (sub-second) |
| POST | `/api/upload/fhir` | Upload FHIR bundle JSON |
| POST | `/api/upload/ehr` | Upload PDF/CSV EHR document |
| POST | `/api/human-feedback` | Doctor edits → re-debate |
| GET | `/api/safety-check` | Drug interaction lookup |
| GET | `/api/classifiers` | List available classifier tools |
| GET | `/api/health` | Health check |
| WS | `/ws/analyze` | WebSocket for streaming analysis |

---

*Last updated: 2026-03-01*

### Known Issues / Notes

- **Analysis time ~100s**: The full debate pipeline makes ~14 LLM calls (3 rounds × 4 agents + synthesis + validation). Each GPT-4o call takes 5-12s. Rounds are inherently serial (round N+1 depends on round N). External API calls (FDA, PubMed, RxNorm) are now parallelized but LLM latency dominates.
- **Debate consensus**: The Critic agent may not reach consensus within 3 rounds for complex cases. This is by design — the case is flagged for human review and the best-effort SOAP is still returned.
- **`requests` version warning**: Cosmetic warning about urllib3/chardet version mismatch — does not affect functionality.
- **DrugBank CSV**: Not included (proprietary). The app warns `DrugBank CSV not found` — this is expected. Download from https://go.drugbank.com/releases if you have a license.
- **macOS SSL**: The app auto-patches `ssl._create_default_https_context` with certifi's cert bundle at startup. This fixes PubMed/spaCy/urllib SSL errors on macOS without requiring manual certificate installation.
- **RxNorm interaction endpoint**: The interaction list endpoint sometimes returns 404 for certain drug combinations. Individual RxCUI lookups work correctly. Drug interaction data primarily comes from the LLM Safety agent + FDA labels.

### Smoke Test Results (Latest)

```
TEST 1: Health Check ................ PASS
TEST 2: Full Analysis Pipeline ...... PASS (102s)
  - SOAP: All 4 sections populated
  - Differentials: 4 (Anemia, Orthostatic Hypotension, CKD Progression, Medication Side Effects)
  - Citations: 4 PubMed references
  - Safety flags: 2 (Lisinopril+K hyperkalemia, Metformin renal dosing)
  - Drug interactions: 1 major (Lisinopril × Potassium)
  - Dosing alerts: 1, Population flags: 1
TEST 3: Emergency Mode .............. PASS (3s)
  - ESI Score: 1 (highest severity)
  - Differentials: 3 (AMI, Cardiogenic Shock, Aortic Dissection)
  - Red flags: 4
TEST 4: Drug Safety Check ........... PASS
TEST 5: Classifiers ................. PASS (4 classifiers available)
```
