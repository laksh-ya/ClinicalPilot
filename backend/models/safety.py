"""
Safety / Drug interaction models for the Medical Error Prevention Panel.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DrugInteraction(BaseModel):
    drug_a: str
    drug_b: str
    severity: str  # "contraindicated", "major", "moderate", "minor"
    description: str
    mechanism: str = ""
    recommendation: str = ""


class DrugDiseaseContraindication(BaseModel):
    drug: str
    disease: str
    severity: str
    description: str
    recommendation: str = ""


class DosingAlert(BaseModel):
    drug: str
    alert_type: str  # "renal", "hepatic", "weight-based", "age-based"
    description: str
    recommendation: str = ""


class PopulationFlag(BaseModel):
    drug: str
    population: str  # "pregnancy", "pediatric", "elderly", "lactation"
    category: str = ""  # e.g. FDA pregnancy category
    description: str
    recommendation: str = ""


class MedErrorPanel(BaseModel):
    """Complete Medical Error Prevention Panel output."""
    drug_interactions: list[DrugInteraction] = Field(default_factory=list)
    contraindications: list[DrugDiseaseContraindication] = Field(default_factory=list)
    dosing_alerts: list[DosingAlert] = Field(default_factory=list)
    population_flags: list[PopulationFlag] = Field(default_factory=list)
    summary: str = ""
