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

### 4. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your actual keys
```

**Minimum required**: Set `OPENAI_API_KEY` in `.env` (for analysis pipeline) and `GROQ_API_KEY` (for AI chat)

### 5. Run the Application

```bash
# Start the FastAPI backend (serves frontend too)
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

---

## Detailed Installation

### Python Dependencies Breakdown

```bash
# Core framework
pip install fastapi uvicorn[standard] python-multipart

# LLM & Agents
pip install openai langchain langchain-openai langchain-community

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

### OpenAI (Required)

1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Add to `.env`:
   ```
   OPENAI_API_KEY=sk-...your-key-here...
   ```

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

### Groq (Required for AI Chat)

1. Go to https://console.groq.com/keys
2. Create a free API key
3. Add to `.env`:
   ```
   GROQ_API_KEY=gsk_...your-key-here...
   GROQ_MODEL=llama-3.3-70b-versatile
   ```

The AI Chat view uses Groq's Llama 3.3 70B for fast conversational clinical Q&A. Without this key, the chat endpoint returns 503 — the rest of the app works fine.

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
# 9B version (~5GB, needs 16GB RAM)
ollama pull medgemma2:9b

# 27B version (~15GB, needs 32GB+ RAM)
ollama pull medgemma2:27b
```

### Configure .env

```
USE_LOCAL_LLM=true
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=medgemma2:9b
```

**Fallback behavior**: If Ollama is unreachable, the system automatically falls back to OpenAI.

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

After setup, verify everything works:

```bash
# 1. Health check
curl http://localhost:8000/api/health

# 2. Test AI Chat (Groq)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What are the red flags for chest pain?"}]}'

# 3. Test with sample case (should return SOAP note — takes ~100s)
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "45-year-old male presenting with acute chest pain radiating to left arm, diaphoresis, and shortness of breath. History of hypertension and type 2 diabetes. Current medications: metformin 1000mg BID, lisinopril 20mg daily."}'

# 4. Test emergency mode
curl -X POST http://localhost:8000/api/emergency \
  -H "Content-Type: application/json" \
  -d '{"text": "Unconscious patient, no pulse, bystander CPR in progress"}'

# 5. Check API docs
open http://localhost:8000/docs
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

### "OPENAI_API_KEY not set"
```bash
cp .env.example .env
# Edit .env and add your key
```

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

*Last updated: 2026-02-28*
