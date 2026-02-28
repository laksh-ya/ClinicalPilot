"""
Final Synthesizer — combines debate outputs into a polished SOAP note.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.models.patient import PatientContext
from backend.models.agents import DebateState
from backend.models.soap import ConfidenceLevel, Differential, SOAPNote
from backend.agents.llm_client import llm_call, load_prompt

logger = logging.getLogger(__name__)


async def synthesize_soap(
    patient: PatientContext,
    debate: DebateState,
) -> SOAPNote:
    """
    Final synthesis step — takes all debate outputs and produces a clean SOAP note.
    """
    system_prompt = load_prompt("synthesizer_system.txt")

    # Build comprehensive context from the last round of debate
    clinical = debate.clinical_outputs[-1] if debate.clinical_outputs else None
    literature = debate.literature_outputs[-1] if debate.literature_outputs else None
    safety = debate.safety_outputs[-1] if debate.safety_outputs else None
    critic = debate.critic_outputs[-1] if debate.critic_outputs else None

    user_message = f"""## Patient Context
{patient.to_clinical_summary()}

## Clinical Agent (Final Round {debate.round_number})
"""
    if clinical:
        ddx = "\n".join(
            f"  {i+1}. {d.diagnosis} ({d.confidence.value}): {d.reasoning}"
            for i, d in enumerate(clinical.differentials)
        )
        user_message += f"""Differentials:
{ddx}
Risk Scores: {clinical.risk_scores}
SOAP Draft: {clinical.soap_draft}
"""

    user_message += "\n## Literature Agent (Final Round)\n"
    if literature:
        evid = "\n".join(
            f"  - {e.title} ({e.journal}, {e.year}): {e.snippet}"
            for e in literature.evidence[:5]
        )
        user_message += f"""Evidence:
{evid}
Summary: {literature.summary}
"""

    user_message += "\n## Safety Agent (Final Round)\n"
    if safety:
        flags = "\n".join(
            f"  - [{f.severity}] {f.description}" for f in safety.flags
        )
        user_message += f"""Flags:
{flags}
Medication Review: {safety.medication_review}
"""

    if critic:
        user_message += f"""
## Critic Assessment
{critic.overall_assessment}
Consensus: {critic.consensus_reached}
Dissent: {critic.dissent_log}
"""

    user_message += f"""
## Debate Info
Rounds completed: {debate.round_number}
Consensus reached: {debate.final_consensus}
Flagged for human review: {debate.flagged_for_human}
"""

    result = await llm_call(
        system_prompt=system_prompt,
        user_message=user_message,
        json_mode=True,
    )

    soap = _parse_soap(result["content"])
    soap.model_used = result.get("model", "")
    soap.total_tokens = result.get("tokens", 0)

    return soap


def _parse_soap(data: Any) -> SOAPNote:
    """Parse synthesizer output into SOAPNote."""
    if isinstance(data, str):
        return SOAPNote(assessment=data)

    differentials = []
    for d in data.get("differentials", []):
        differentials.append(
            Differential(
                diagnosis=d.get("diagnosis", ""),
                likelihood=d.get("likelihood", ""),
                reasoning=d.get("reasoning", ""),
                confidence=_conf(d.get("confidence", "medium")),
                supporting_evidence=d.get("supporting_evidence", []),
            )
        )

    return SOAPNote(
        subjective=data.get("subjective", ""),
        objective=data.get("objective", ""),
        assessment=data.get("assessment", ""),
        plan=data.get("plan", ""),
        differentials=differentials,
        risk_scores=data.get("risk_scores", {}),
        uncertainty=_conf(data.get("uncertainty", "medium")),
        uncertainty_reasoning=data.get("uncertainty_reasoning", ""),
        citations=data.get("citations", []),
        safety_flags=data.get("safety_flags", []),
        debate_summary=data.get("debate_summary", ""),
        dissent_log=data.get("dissent_log", []),
    )


def _conf(val: str) -> ConfidenceLevel:
    try:
        return ConfidenceLevel(val.lower())
    except (ValueError, AttributeError):
        return ConfidenceLevel.MEDIUM
