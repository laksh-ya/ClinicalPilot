"""
Orchestrator — routes requests through the full pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time

from backend.models.patient import AnalysisRequest, PatientContext
from backend.models.soap import SOAPNote
from backend.models.agents import DebateState
from backend.input_layer.text_parser import parse_text_input
from backend.input_layer.fhir_parser import parse_fhir_bundle
from backend.input_layer.anonymizer import get_anonymizer
from backend.config import get_settings

logger = logging.getLogger(__name__)


async def full_pipeline(request: AnalysisRequest) -> tuple[SOAPNote, DebateState]:
    """
    Run the complete ClinicalPilot pipeline:
    Input → Anonymize → Parse → Agents (parallel) → Debate → Synthesize → Validate
    
    Returns: (final SOAP note, debate state for UI)
    """
    start = time.monotonic()
    settings = get_settings()

    # ── Step 1: Build PatientContext ──────────────────────
    if request.patient_context:
        patient = request.patient_context
    elif request.fhir_bundle:
        patient = parse_fhir_bundle(request.fhir_bundle)
    else:
        # Anonymize text input
        anon = get_anonymizer(settings.spacy_model)
        clean_text = anon.anonymize(request.text)
        patient = parse_text_input(clean_text)

    if not patient.current_prompt and request.text:
        patient.current_prompt = request.text

    # ── Step 2: Run debate ────────────────────────────────
    from backend.debate.debate_engine import run_debate

    debate_state = await run_debate(patient, max_rounds=settings.max_debate_rounds)

    # ── Step 3: Synthesize final output ──────────────────
    from backend.validation.synthesizer import synthesize_soap

    soap = await synthesize_soap(patient, debate_state)
    soap.latency_ms = int((time.monotonic() - start) * 1000)

    # ── Step 4: Validate ─────────────────────────────────
    from backend.validation.validator import validate_output

    soap = validate_output(soap)

    return soap, debate_state
