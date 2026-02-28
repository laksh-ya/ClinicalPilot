"""
Patient & Unified Schema models.
All parsers produce a PatientContext — the common currency for all agents.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class Condition(BaseModel):
    code: str = ""
    display: str
    onset_date: Optional[str] = None
    status: str = "active"


class Medication(BaseModel):
    name: str
    dose: str = ""
    frequency: str = ""
    route: str = "oral"
    status: str = "active"


class LabResult(BaseModel):
    name: str
    value: str
    unit: str = ""
    reference_range: str = ""
    date: Optional[str] = None
    flag: str = ""  # "high", "low", "critical", ""


class Vital(BaseModel):
    name: str  # e.g. "blood_pressure", "heart_rate"
    value: str
    unit: str = ""
    date: Optional[str] = None


class Allergy(BaseModel):
    substance: str
    reaction: str = ""
    severity: str = ""  # mild, moderate, severe


class PatientContext(BaseModel):
    """
    Unified schema — the single data structure that all parsers output
    and all agents consume.
    """

    # Demographics
    age: Optional[int] = None
    gender: Gender = Gender.UNKNOWN
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None

    # Clinical data
    conditions: list[Condition] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    labs: list[LabResult] = Field(default_factory=list)
    vitals: list[Vital] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)

    # The current clinical prompt / question
    current_prompt: str = ""

    # Raw text (anonymised) for agents that want full context
    raw_text: str = ""

    # Source metadata
    source_type: str = "text"  # "fhir", "ehr_pdf", "ehr_csv", "text"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_clinical_summary(self) -> str:
        """Render a concise clinical summary string for LLM prompts."""
        parts: list[str] = []

        # Demographics
        demo = []
        if self.age:
            demo.append(f"{self.age}-year-old")
        if self.gender != Gender.UNKNOWN:
            demo.append(self.gender.value)
        if demo:
            parts.append(" ".join(demo) + " patient")

        # Conditions
        if self.conditions:
            conds = ", ".join(c.display for c in self.conditions)
            parts.append(f"PMH: {conds}")

        # Medications
        if self.medications:
            meds = ", ".join(
                f"{m.name} {m.dose} {m.frequency}".strip() for m in self.medications
            )
            parts.append(f"Medications: {meds}")

        # Allergies
        if self.allergies:
            allg = ", ".join(a.substance for a in self.allergies)
            parts.append(f"Allergies: {allg}")

        # Labs
        if self.labs:
            labs = ", ".join(
                f"{l.name}: {l.value} {l.unit}".strip() for l in self.labs
            )
            parts.append(f"Labs: {labs}")

        # Vitals
        if self.vitals:
            vits = ", ".join(
                f"{v.name}: {v.value} {v.unit}".strip() for v in self.vitals
            )
            parts.append(f"Vitals: {vits}")

        # Current prompt
        if self.current_prompt:
            parts.append(f"Presenting complaint: {self.current_prompt}")

        return "\n".join(parts) if parts else self.raw_text or self.current_prompt


class AnalysisRequest(BaseModel):
    """Top-level API request for /api/analyze and /api/emergency."""
    text: str = ""
    fhir_bundle: Optional[dict] = None
    patient_context: Optional[PatientContext] = None
