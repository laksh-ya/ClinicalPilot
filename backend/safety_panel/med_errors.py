"""
Medical Error Prevention Panel — runs drug interaction and safety checks.
Runs as a sidebar on every case.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import get_settings
from backend.models.patient import PatientContext
from backend.models.safety import (
    DosingAlert,
    DrugDiseaseContraindication,
    DrugInteraction,
    MedErrorPanel,
    PopulationFlag,
)
from backend.agents.llm_client import llm_call

logger = logging.getLogger(__name__)

MED_ERROR_SYSTEM_PROMPT = """You are a clinical pharmacist AI performing a comprehensive medication safety review.

Given patient medications, conditions, demographics, and labs, perform ALL of these checks:

1. Drug-Drug Interactions — check every medication pair
2. Drug-Disease Contraindications — check each drug against each condition
3. Dosing Alerts — check for renal/hepatic/weight/age adjustments needed
4. Population Flags — check for pregnancy/pediatric/elderly/lactation concerns

For each finding, provide:
- The specific issue
- The mechanism in plain language
- A clear recommendation

Respond with JSON:
{
  "drug_interactions": [{"drug_a": "...", "drug_b": "...", "severity": "contraindicated|major|moderate|minor", "description": "...", "mechanism": "...", "recommendation": "..."}],
  "contraindications": [{"drug": "...", "disease": "...", "severity": "...", "description": "...", "recommendation": "..."}],
  "dosing_alerts": [{"drug": "...", "alert_type": "renal|hepatic|weight-based|age-based", "description": "...", "recommendation": "..."}],
  "population_flags": [{"drug": "...", "population": "pregnancy|pediatric|elderly|lactation", "category": "...", "description": "...", "recommendation": "..."}],
  "summary": "Overall safety assessment..."
}
"""


async def run_med_error_panel(patient: PatientContext) -> MedErrorPanel:
    """
    Run the Medical Error Prevention Panel.
    
    This runs on EVERY case, not just drug-specific queries.
    """
    if not patient.medications:
        return MedErrorPanel(summary="No medications found in patient data.")

    # Build context
    meds = "\n".join(
        f"- {m.name} {m.dose} {m.frequency} ({m.route})".strip()
        for m in patient.medications
    )
    conditions = "\n".join(f"- {c.display}" for c in patient.conditions) if patient.conditions else "Not specified"
    
    demographics = []
    if patient.age:
        demographics.append(f"Age: {patient.age}")
    if patient.gender.value != "unknown":
        demographics.append(f"Gender: {patient.gender.value}")
    if patient.weight_kg:
        demographics.append(f"Weight: {patient.weight_kg} kg")
    demo_text = ", ".join(demographics) if demographics else "Not specified"

    labs = "\n".join(
        f"- {l.name}: {l.value} {l.unit} (ref: {l.reference_range})"
        for l in patient.labs
    ) if patient.labs else "Not available"

    allergies = ", ".join(a.substance for a in patient.allergies) if patient.allergies else "NKDA"

    user_message = f"""## Medications
{meds}

## Conditions
{conditions}

## Demographics
{demo_text}

## Labs
{labs}

## Allergies
{allergies}
"""

    settings = get_settings()
    result = await llm_call(
        system_prompt=MED_ERROR_SYSTEM_PROMPT,
        user_message=user_message,
        json_mode=True,
    )

    return _parse_panel(result["content"])


def _parse_panel(data: Any) -> MedErrorPanel:
    """Parse LLM response into MedErrorPanel."""
    if isinstance(data, str):
        return MedErrorPanel(summary=data)

    interactions = [
        DrugInteraction(**i) for i in data.get("drug_interactions", [])
        if isinstance(i, dict)
    ]
    contras = [
        DrugDiseaseContraindication(**c) for c in data.get("contraindications", [])
        if isinstance(c, dict)
    ]
    dosing = [
        DosingAlert(**d) for d in data.get("dosing_alerts", [])
        if isinstance(d, dict)
    ]
    population = [
        PopulationFlag(**p) for p in data.get("population_flags", [])
        if isinstance(p, dict)
    ]

    return MedErrorPanel(
        drug_interactions=interactions,
        contraindications=contras,
        dosing_alerts=dosing,
        population_flags=population,
        summary=data.get("summary", ""),
    )
