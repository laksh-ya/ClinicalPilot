"""
ClinicalPilot — FastAPI Backend Server

Serves:
- REST API for all clinical analysis endpoints
- WebSocket for streaming analysis
- Static frontend files
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

# Fix macOS SSL certificate verification globally.
# On macOS, Python's urllib doesn't trust the system cert store.
# This patches ssl so ALL urllib-based calls (BioPython Entrez,
# spaCy model downloads, etc.) use certifi's cert bundle.
import os as _os
import ssl as _ssl
try:
    import certifi as _certifi
    _cert_file = _certifi.where()
    # Patch in-process urllib/http.client default SSL context
    _ssl._create_default_https_context = (
        lambda: _ssl.create_default_context(cafile=_cert_file)
    )
    # Set env vars so child processes (pip, spaCy download) also trust certs
    _os.environ.setdefault("SSL_CERT_FILE", _cert_file)
    _os.environ.setdefault("REQUESTS_CA_BUNDLE", _cert_file)
except ImportError:
    pass

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings, PROJECT_ROOT, set_runtime_override, get_effective
from backend.models.patient import AnalysisRequest, PatientContext
from backend.models.soap import SOAPNote, EmergencyOutput
from backend.models.safety import MedErrorPanel

# ── Logging ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("clinicalpilot")

# ── App ─────────────────────────────────────────────────
app = FastAPI(
    title="ClinicalPilot",
    description="Multi-agent clinical decision support system with debate-driven reasoning",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ────────────────────────────────────────────────
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Startup ─────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("ClinicalPilot starting up...")
    
    # Setup observability
    try:
        from backend.observability.tracing import setup_tracing
        tracing = setup_tracing()
        logger.info(f"Tracing enabled: {tracing}")
    except Exception as e:
        logger.warning(f"Tracing setup failed: {e}")

    logger.info("ClinicalPilot ready.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  API ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "clinicalpilot",
        "version": "1.0.0",
        "model": settings.openai_model,
        "local_llm": settings.use_local_llm,
    }


@app.get("/api/config-status")
async def config_status():
    """Return which LLM providers are configured and active."""
    openai_key = get_effective("openai_api_key")
    groq_key = get_effective("groq_api_key")
    has_openai = bool(openai_key)
    has_groq = bool(groq_key)

    if has_openai:
        active_provider = "openai"
    elif has_groq:
        active_provider = "groq"
    elif settings.use_local_llm:
        active_provider = "ollama"
    else:
        active_provider = "none"

    return {
        "has_openai_key": has_openai,
        "has_groq_key": has_groq,
        "use_local_llm": settings.use_local_llm,
        "active_provider": active_provider,
        "openai_model": settings.openai_model,
        "groq_model": settings.groq_model,
    }


@app.post("/api/set-api-key")
async def set_api_key(payload: dict):
    """
    Set OpenAI API key at runtime (stored in memory only, not persisted).
    Accepts {openai_api_key: "sk-..."} and/or {groq_api_key: "gsk_..."}.
    """
    updated = []

    openai_key = payload.get("openai_api_key", "").strip()
    if openai_key:
        set_runtime_override("openai_api_key", openai_key)
        updated.append("openai_api_key")
        logger.info("OpenAI API key set via runtime override")

    groq_key = payload.get("groq_api_key", "").strip()
    if groq_key:
        set_runtime_override("groq_api_key", groq_key)
        updated.append("groq_api_key")
        logger.info("Groq API key set via runtime override")

    if not updated:
        raise HTTPException(400, "No valid API key provided")

    return {"status": "ok", "updated": updated}


@app.post("/api/analyze", response_model=dict)
async def analyze(request: AnalysisRequest):
    """
    Full analysis pipeline.
    Input → Anonymize → Parse → Multi-Agent Debate → SOAP Note
    """
    if not request.text and not request.fhir_bundle and not request.patient_context:
        raise HTTPException(400, "Must provide text, fhir_bundle, or patient_context")

    try:
        from backend.agents.orchestrator import full_pipeline
        from backend.safety_panel.med_errors import run_med_error_panel
        from backend.input_layer.text_parser import parse_text_input

        # Get patient context for med error panel
        if request.patient_context:
            patient = request.patient_context
        else:
            patient = parse_text_input(request.text)

        # Run full pipeline and med error panel IN PARALLEL
        pipeline_task = full_pipeline(request)
        med_panel_task = run_med_error_panel(patient)

        (soap, debate_state), med_panel = await asyncio.gather(
            pipeline_task, med_panel_task
        )

        return {
            "soap": soap.model_dump(),
            "debate": debate_state.model_dump(),
            "med_error_panel": med_panel.model_dump(),
        }
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(500, f"Analysis failed: {str(e)}")


@app.post("/api/emergency", response_model=dict)
async def emergency(request: AnalysisRequest):
    """
    Emergency Mode — fast-path triage.
    Bypasses debate, targets <5s response.
    """
    if not request.text:
        raise HTTPException(400, "Must provide text for emergency mode")

    try:
        from backend.emergency.emergency import emergency_analyze

        result = await emergency_analyze(request.text)
        return {"emergency": result.model_dump()}
    except Exception as e:
        logger.exception("Emergency analysis failed")
        raise HTTPException(500, f"Emergency analysis failed: {str(e)}")


@app.post("/api/upload/fhir", response_model=dict)
async def upload_fhir(bundle: dict):
    """Upload a FHIR R4 Bundle for analysis."""
    try:
        from backend.input_layer.fhir_parser import parse_fhir_bundle

        patient = parse_fhir_bundle(bundle)
        return {
            "patient_context": patient.model_dump(),
            "summary": patient.to_clinical_summary(),
        }
    except Exception as e:
        logger.exception("FHIR parsing failed")
        raise HTTPException(500, f"FHIR parsing failed: {str(e)}")


@app.post("/api/upload/ehr", response_model=dict)
async def upload_ehr(file: UploadFile = File(...)):
    """Upload a PDF or CSV EHR document for parsing."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    file_bytes = await file.read()

    try:
        if file.filename.lower().endswith(".pdf"):
            from backend.input_layer.ehr_parser import parse_ehr_pdf
            patient = await parse_ehr_pdf(file_bytes, file.filename)
        elif file.filename.lower().endswith(".csv"):
            from backend.input_layer.ehr_parser import parse_ehr_csv
            patient = await parse_ehr_csv(file_bytes, file.filename)
        else:
            raise HTTPException(400, "Unsupported file type. Use PDF or CSV.")

        return {
            "patient_context": patient.model_dump(),
            "summary": patient.to_clinical_summary(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("EHR parsing failed")
        raise HTTPException(500, f"EHR parsing failed: {str(e)}")


@app.post("/api/human-feedback", response_model=dict)
async def human_feedback(payload: dict):
    """
    Human-in-the-loop: doctor edits SOAP → triggers re-debate (max 1 iteration).
    """
    edited_soap = payload.get("edited_soap", "")
    original_text = payload.get("original_text", "")
    feedback = payload.get("feedback", "")

    if not edited_soap and not feedback:
        raise HTTPException(400, "Must provide edited_soap or feedback")

    try:
        from backend.agents.orchestrator import full_pipeline
        from backend.models.patient import AnalysisRequest

        # Re-run with feedback as additional context
        enhanced_text = f"{original_text}\n\n---\nDoctor Feedback: {feedback}\nEdited SOAP: {edited_soap}"
        request = AnalysisRequest(text=enhanced_text)
        soap, debate_state = await full_pipeline(request)

        return {
            "soap": soap.model_dump(),
            "debate": debate_state.model_dump(),
            "note": "Re-analysis with human feedback completed",
        }
    except Exception as e:
        logger.exception("Human feedback re-analysis failed")
        raise HTTPException(500, str(e))


@app.get("/api/safety-check")
async def safety_check(drugs: str = ""):
    """
    Quick drug interaction lookup.
    Query param: drugs=metformin,lisinopril,aspirin
    """
    if not drugs:
        raise HTTPException(400, "Provide comma-separated drug names in 'drugs' param")

    drug_list = [d.strip() for d in drugs.split(",") if d.strip()]

    results = {}

    # RxNorm interactions
    try:
        from backend.external.rxnorm import check_interactions_rxnorm

        rxnorm_results = await check_interactions_rxnorm(drug_list)
        results["rxnorm_interactions"] = rxnorm_results
    except Exception as e:
        results["rxnorm_interactions"] = f"Error: {e}"

    # DrugBank lookup
    try:
        from backend.external.drugbank import lookup_interactions

        db_results = lookup_interactions(drug_list)
        results["drugbank"] = db_results
    except Exception as e:
        results["drugbank"] = f"Error: {e}"

    return results


@app.get("/api/classifiers")
async def get_classifiers():
    """List available medical image classifier tools."""
    return {
        "classifiers": [
            {
                "name": "Lung Disease Classifier",
                "description": "AI-powered lung disease classification from chest X-rays",
                "url": "https://lung-disease-classification.streamlit.app/",
                "icon": "🫁",
                "embed": True,
            },
            {
                "name": "Chest Disease Classifier",
                "description": "AI chest disease detection and analysis",
                "url": "https://caryaai.streamlit.app/",
                "icon": "🫀",
                "embed": True,
            },
            {
                "name": "AI Retina Analyser",
                "description": "Diabetic retinopathy detection from retinal images",
                "url": "https://retinopathy-detection.streamlit.app/",
                "icon": "👁️",
                "embed": True,
            },
            {
                "name": "Skin Cancer Detector",
                "description": "Skin lesion classification for melanoma screening",
                "url": "https://skincancer-detection.streamlit.app/",
                "icon": "🔬",
                "embed": True,
            },
        ]
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AI CHAT (Groq — lightweight, no agents)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHAT_SYSTEM_PROMPT = """You are ClinicalPilot AI, a clinical decision-support assistant for healthcare professionals.

Your role:
- Answer clinical questions with evidence-based, concise responses.
- Help with differential diagnoses, drug interactions, guideline lookups, lab interpretation, and clinical reasoning.
- Always cite relevant guidelines (e.g., ACC/AHA, WHO, UpToDate) when applicable.
- If a question involves patient safety, flag it clearly.
- Use structured formatting (bullet points, numbered lists) for clarity.
- If you are unsure, say so — never fabricate clinical information.

You are NOT a replacement for clinical judgment. Always remind users that your answers are for educational/decision-support purposes only.

IMPORTANT: In future you will have access to a LanceDB vector store with indexed medical literature for RAG-enhanced answers. For now, rely on your training knowledge."""


@app.post("/api/chat")
async def chat(payload: dict):
    """
    AI chat — tries OpenAI first, falls back to Groq.
    Accepts {messages: [{role, content}, ...]} with conversation history.
    """
    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(400, "No messages provided")

    openai_key = get_effective("openai_api_key")
    groq_key = get_effective("groq_api_key")

    if not openai_key and not groq_key:
        raise HTTPException(
            503,
            "No LLM API key configured. Please set your OpenAI API key in Settings, or add GROQ_API_KEY to .env"
        )

    full_messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}] + [
        {"role": m["role"], "content": m["content"]} for m in messages
    ]

    # Try OpenAI first
    if openai_key:
        try:
            from openai import OpenAI as SyncOpenAI

            client = SyncOpenAI(api_key=openai_key)

            t0 = time.time()
            completion = client.chat.completions.create(
                model=settings.openai_model,
                messages=full_messages,
                temperature=0.3,
                max_tokens=2048,
            )
            latency_ms = int((time.time() - t0) * 1000)

            reply = completion.choices[0].message.content
            return {
                "reply": reply,
                "model": settings.openai_model,
                "provider": "openai",
                "latency_ms": latency_ms,
                "tokens": getattr(completion.usage, "total_tokens", None),
            }
        except Exception as e:
            logger.warning(f"OpenAI chat failed ({e}), falling back to Groq")
            if not groq_key:
                raise HTTPException(500, f"OpenAI chat failed and no Groq fallback: {str(e)}")

    # Fallback to Groq
    try:
        from groq import Groq

        client = Groq(api_key=groq_key)

        t0 = time.time()
        completion = client.chat.completions.create(
            model=settings.groq_model,
            messages=full_messages,
            temperature=0.3,
            max_tokens=2048,
        )
        latency_ms = int((time.time() - t0) * 1000)

        reply = completion.choices[0].message.content
        return {
            "reply": reply,
            "model": settings.groq_model,
            "provider": "groq",
            "latency_ms": latency_ms,
            "tokens": getattr(completion.usage, "total_tokens", None),
        }
    except Exception as e:
        logger.exception("Chat failed on all providers")
        raise HTTPException(500, f"Chat failed: {str(e)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WEBSOCKET (Streaming Analysis)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.websocket("/ws/analyze")
async def ws_analyze(websocket: WebSocket):
    """WebSocket endpoint for streaming analysis progress."""
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        text = data.get("text", "")

        if not text:
            await websocket.send_json({"error": "No text provided"})
            await websocket.close()
            return

        # Stream progress updates
        async def send_status(stage: str, detail: str = ""):
            await websocket.send_json({"type": "status", "stage": stage, "detail": detail})

        await send_status("parsing", "Parsing clinical input...")

        from backend.input_layer.anonymizer import get_anonymizer
        from backend.input_layer.text_parser import parse_text_input

        anon = get_anonymizer(settings.spacy_model)
        clean_text = anon.anonymize(text)
        patient = parse_text_input(clean_text)
        patient.current_prompt = text

        await send_status("agents", "Running Clinical Agent...")

        from backend.agents.clinical import run_clinical_agent
        clinical = await run_clinical_agent(patient)
        await websocket.send_json({
            "type": "agent_result",
            "agent": "clinical",
            "data": clinical.model_dump(),
        })

        await send_status("agents", "Running Literature & Safety Agents...")

        from backend.agents.literature import run_literature_agent
        from backend.agents.safety import run_safety_agent

        literature, safety = await asyncio.gather(
            run_literature_agent(patient, clinical_output=clinical),
            run_safety_agent(patient, proposed_plan=clinical.soap_draft),
        )

        await websocket.send_json({
            "type": "agent_result",
            "agent": "literature",
            "data": literature.model_dump(),
        })
        await websocket.send_json({
            "type": "agent_result",
            "agent": "safety",
            "data": safety.model_dump(),
        })

        await send_status("debate", "Critic Agent reviewing...")

        from backend.agents.critic import run_critic_agent
        critic = await run_critic_agent(patient, clinical, literature, safety)
        await websocket.send_json({
            "type": "agent_result",
            "agent": "critic",
            "data": critic.model_dump(),
        })

        await send_status("synthesis", "Generating final SOAP note...")

        from backend.models.agents import DebateState
        debate_state = DebateState(
            round_number=1,
            clinical_outputs=[clinical],
            literature_outputs=[literature],
            safety_outputs=[safety],
            critic_outputs=[critic],
            final_consensus=critic.consensus_reached,
        )

        from backend.validation.synthesizer import synthesize_soap
        from backend.validation.validator import validate_output

        soap = await synthesize_soap(patient, debate_state)
        soap = validate_output(soap)

        await send_status("safety_panel", "Running medication safety panel...")

        from backend.safety_panel.med_errors import run_med_error_panel
        med_panel = await run_med_error_panel(patient)

        # Send final result
        await websocket.send_json({
            "type": "complete",
            "soap": soap.model_dump(),
            "debate": debate_state.model_dump(),
            "med_error_panel": med_panel.model_dump(),
        })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.exception("WebSocket analysis failed")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATIC FRONTEND
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FRONTEND_DIR = PROJECT_ROOT / "frontend"


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>ClinicalPilot</h1><p>Frontend not found. Place files in /frontend/</p>")


# Mount static files (CSS, JS, assets)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
