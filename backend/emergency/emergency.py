"""
Emergency Mode — fast-path clinical decision support.

Bypasses the debate layer entirely.
Clinical + Safety agents run in parallel.
Target: <5 second response.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.config import get_settings
from backend.models.patient import PatientContext
from backend.models.soap import ConfidenceLevel, Differential, EmergencyOutput
from backend.agents.llm_client import llm_call, load_prompt
from backend.input_layer.text_parser import parse_text_input

logger = logging.getLogger(__name__)


async def emergency_analyze(text: str) -> EmergencyOutput:
    """
    Emergency mode — fast clinical triage.
    
    Bypasses:
    - Full anonymization (speed > privacy in true emergencies)
    - Debate layer (no multi-round, just direct output)
    - Literature search (too slow)
    
    Runs: Emergency triage + Safety check in parallel.
    """
    start = time.monotonic()
    settings = get_settings()

    # Quick parse
    patient = parse_text_input(text)

    # Run emergency triage and safety in parallel
    triage_task = _run_emergency_triage(patient)
    safety_task = _run_quick_safety(patient)

    triage_result, safety_result = await asyncio.gather(
        triage_task, safety_task, return_exceptions=True
    )

    # Build output
    output = EmergencyOutput()

    if isinstance(triage_result, EmergencyOutput):
        output = triage_result
    elif isinstance(triage_result, Exception):
        logger.error(f"Emergency triage failed: {triage_result}")
        output.call_to_action = "⚠️ AI triage failed — use clinical judgment. Call for backup."

    if isinstance(safety_result, list):
        output.safety_flags.extend(safety_result)
    elif isinstance(safety_result, Exception):
        logger.error(f"Quick safety check failed: {safety_result}")

    output.latency_ms = int((time.monotonic() - start) * 1000)
    return output


async def _run_emergency_triage(patient: PatientContext) -> EmergencyOutput:
    """Run the emergency triage agent."""
    system_prompt = load_prompt("emergency_system.txt")

    user_message = f"""EMERGENCY CASE:
{patient.current_prompt or patient.raw_text}

Patient info: {patient.to_clinical_summary()}

RESPOND IMMEDIATELY. Top 3 differentials, red flags, ESI score, and call to action.
"""

    result = await llm_call(
        system_prompt=system_prompt,
        user_message=user_message,
        json_mode=True,
        max_tokens=1500,  # Keep response short for speed
        temperature=0.1,  # More deterministic in emergencies
    )

    return _parse_emergency(result["content"])


async def _run_quick_safety(patient: PatientContext) -> list[str]:
    """Quick medication safety check — no full agent, just flag obvious issues."""
    if not patient.medications:
        return []

    # Simple LLM check for immediate safety concerns
    meds = ", ".join(m.name for m in patient.medications)
    conditions = ", ".join(c.display for c in patient.conditions) if patient.conditions else "unknown"

    system_prompt = (
        "You are an emergency medication safety checker. "
        "Given medications and conditions, list ONLY critical safety issues. "
        "Respond with JSON: {\"flags\": [\"issue1\", \"issue2\"]}"
    )

    user_message = f"Medications: {meds}\nConditions: {conditions}"

    try:
        settings = get_settings()
        result = await llm_call(
            system_prompt=system_prompt,
            user_message=user_message,
            model=settings.openai_fast_model,
            json_mode=True,
            max_tokens=500,
        )
        data = result["content"]
        if isinstance(data, dict):
            return data.get("flags", [])
        return []
    except Exception as e:
        logger.warning(f"Quick safety check failed: {e}")
        return []


def _parse_emergency(data: Any) -> EmergencyOutput:
    """Parse emergency triage response."""
    if isinstance(data, str):
        return EmergencyOutput(call_to_action=data)

    differentials = []
    for d in data.get("top_differentials", []):
        differentials.append(
            Differential(
                diagnosis=d.get("diagnosis", ""),
                likelihood=d.get("likelihood", ""),
                reasoning=d.get("reasoning", ""),
                confidence=_conf(d.get("confidence", "medium")),
                supporting_evidence=d.get("supporting_evidence", []),
            )
        )

    return EmergencyOutput(
        top_differentials=differentials,
        red_flags=data.get("red_flags", []),
        call_to_action=data.get("call_to_action", ""),
        esi_score=data.get("esi_score"),
        safety_flags=data.get("safety_flags", []),
    )


def _conf(val: str) -> ConfidenceLevel:
    try:
        return ConfidenceLevel(val.lower())
    except (ValueError, AttributeError):
        return ConfidenceLevel.MEDIUM
