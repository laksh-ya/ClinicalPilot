"""
Safety Agent — checks for drug interactions, contraindications, dosing alerts.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.models.patient import PatientContext
from backend.models.agents import SafetyAgentOutput, SafetyFlag
from .llm_client import llm_call, load_prompt

logger = logging.getLogger(__name__)


async def run_safety_agent(
    patient: PatientContext,
    proposed_plan: str = "",
    critique: str = "",
) -> SafetyAgentOutput:
    """
    Run the Safety Agent — checks for medication safety issues.
    
    Args:
        patient: Unified patient context
        proposed_plan: Optional treatment plan from Clinical Agent to check
        critique: Optional critique from previous debate round
    """
    system_prompt = load_prompt("safety_system.txt")

    user_message = f"""## Patient Context
{patient.to_clinical_summary()}
"""

    # Pull FDA / DrugBank data if available
    external_data = await _get_external_safety_data(patient)
    if external_data:
        user_message += f"""
## External Safety Database Results
{external_data}
"""

    if proposed_plan:
        user_message += f"""
## Proposed Treatment Plan (check for safety issues)
{proposed_plan}
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


async def _get_external_safety_data(patient: PatientContext) -> str:
    """Query external safety databases for known interactions."""
    if not patient.medications:
        return ""

    results = []

    # Try FDA API
    try:
        from backend.external.fda import check_drug_interactions

        drug_names = [m.name for m in patient.medications]
        fda_results = await check_drug_interactions(drug_names)
        if fda_results:
            results.append(f"FDA Data:\n{fda_results}")
    except Exception as e:
        logger.debug(f"FDA lookup skipped: {e}")

    # Try DrugBank
    try:
        from backend.external.drugbank import lookup_interactions

        drug_names = [m.name for m in patient.medications]
        db_results = lookup_interactions(drug_names)
        if db_results:
            results.append(f"DrugBank Data:\n{db_results}")
    except Exception as e:
        logger.debug(f"DrugBank lookup skipped: {e}")

    return "\n\n".join(results)


def _parse_output(data: Any) -> SafetyAgentOutput:
    """Parse LLM JSON response into typed output."""
    if isinstance(data, str):
        return SafetyAgentOutput(medication_review=data)

    flags = []
    for f in data.get("flags", []):
        flags.append(
            SafetyFlag(
                category=f.get("category", ""),
                severity=f.get("severity", "moderate"),
                description=f.get("description", ""),
                mechanism=f.get("mechanism", ""),
                recommendation=f.get("recommendation", ""),
                drugs_involved=f.get("drugs_involved", []),
            )
        )

    return SafetyAgentOutput(
        flags=flags,
        medication_review=data.get("medication_review", ""),
        dosing_alerts=data.get("dosing_alerts", []),
        population_warnings=data.get("population_warnings", []),
    )
