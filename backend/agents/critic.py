"""
Critic Agent — reviews all agent outputs and identifies contradictions, gaps, and errors.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.models.patient import PatientContext
from backend.models.agents import (
    ClinicalAgentOutput,
    CriticOutput,
    LiteratureAgentOutput,
    SafetyAgentOutput,
)
from .llm_client import llm_call, load_prompt

logger = logging.getLogger(__name__)


async def run_critic_agent(
    patient: PatientContext,
    clinical: ClinicalAgentOutput,
    literature: LiteratureAgentOutput,
    safety: SafetyAgentOutput,
) -> CriticOutput:
    """
    Run the Critic Agent — reviews and challenges all agent outputs.
    """
    system_prompt = load_prompt("critic_system.txt")

    # Build comprehensive review input
    ddx_text = "\n".join(
        f"  {i+1}. {d.diagnosis} ({d.likelihood}, {d.confidence.value} confidence): {d.reasoning}"
        for i, d in enumerate(clinical.differentials)
    )

    evidence_text = "\n".join(
        f"  - {e.title} ({e.journal}, {e.year}): {e.snippet}"
        for e in literature.evidence[:5]
    )

    safety_text = "\n".join(
        f"  - [{f.severity.upper()}] {f.description} → {f.recommendation}"
        for f in safety.flags
    )

    user_message = f"""## Original Patient Context
{patient.to_clinical_summary()}

## Clinical Agent Output
Differentials:
{ddx_text or "  (none provided)"}

Risk Scores: {clinical.risk_scores or "None calculated"}

SOAP Draft:
{clinical.soap_draft or "(none)"}

Reasoning: {clinical.reasoning_trace or "(none)"}

## Literature Agent Output
Evidence:
{evidence_text or "  (no evidence found)"}

Summary: {literature.summary}
Contradictions noted: {literature.contradictions or "None"}

## Safety Agent Output
Flags:
{safety_text or "  (no flags)"}

Medication Review: {safety.medication_review}
Dosing Alerts: {safety.dosing_alerts or "None"}
Population Warnings: {safety.population_warnings or "None"}
"""

    result = await llm_call(
        system_prompt=system_prompt,
        user_message=user_message,
        json_mode=True,
    )

    return _parse_output(result["content"])


def _parse_output(data: Any) -> CriticOutput:
    """Parse LLM JSON response into CriticOutput."""
    if isinstance(data, str):
        return CriticOutput(overall_assessment=data)

    return CriticOutput(
        ehr_contradictions=data.get("ehr_contradictions", []),
        evidence_gaps=data.get("evidence_gaps", []),
        safety_misses=data.get("safety_misses", []),
        overall_assessment=data.get("overall_assessment", ""),
        consensus_reached=data.get("consensus_reached", False),
        dissent_log=data.get("dissent_log", []),
    )
