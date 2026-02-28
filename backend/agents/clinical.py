"""
Clinical Agent — generates differential diagnoses, risk scores, and SOAP drafts.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.models.patient import PatientContext
from backend.models.agents import ClinicalAgentOutput
from backend.models.soap import ConfidenceLevel, Differential
from .llm_client import llm_call, load_prompt

logger = logging.getLogger(__name__)


async def run_clinical_agent(
    patient: PatientContext,
    critique: str = "",
) -> ClinicalAgentOutput:
    """
    Run the Clinical Agent on the given patient context.
    
    Args:
        patient: Unified patient context
        critique: Optional critique from previous debate round
    """
    system_prompt = load_prompt("clinical_system.txt")

    user_message = f"""## Patient Context
{patient.to_clinical_summary()}

## Raw Clinical Text
{patient.raw_text or patient.current_prompt}
"""

    if critique:
        user_message += f"""
## Critique from Previous Round (address these issues)
{critique}
"""

    result = await llm_call(
        system_prompt=system_prompt,
        user_message=user_message,
        json_mode=True,
    )

    return _parse_output(result["content"])


def _parse_output(data: Any) -> ClinicalAgentOutput:
    """Parse LLM JSON response into typed output."""
    if isinstance(data, str):
        return ClinicalAgentOutput(soap_draft=data, reasoning_trace=data)

    differentials = []
    for d in data.get("differentials", []):
        differentials.append(
            Differential(
                diagnosis=d.get("diagnosis", ""),
                likelihood=d.get("likelihood", ""),
                reasoning=d.get("reasoning", ""),
                confidence=_parse_confidence(d.get("confidence", "medium")),
                supporting_evidence=d.get("supporting_evidence", []),
            )
        )

    return ClinicalAgentOutput(
        differentials=differentials,
        risk_scores=data.get("risk_scores", {}),
        soap_draft=data.get("soap_draft", ""),
        reasoning_trace=data.get("reasoning_trace", ""),
        confidence=_parse_confidence(data.get("confidence", "medium")),
    )


def _parse_confidence(val: str) -> ConfidenceLevel:
    try:
        return ConfidenceLevel(val.lower())
    except (ValueError, AttributeError):
        return ConfidenceLevel.MEDIUM
