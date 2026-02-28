"""
Agent input / output models — used by orchestrator and debate layer.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .soap import ConfidenceLevel, Differential


class ClinicalAgentOutput(BaseModel):
    differentials: list[Differential] = Field(default_factory=list)
    risk_scores: dict[str, str] = Field(default_factory=dict)
    soap_draft: str = ""
    reasoning_trace: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class LiteratureHit(BaseModel):
    title: str
    authors: str = ""
    journal: str = ""
    year: str = ""
    pmid: str = ""
    snippet: str = ""
    relevance: ConfidenceLevel = ConfidenceLevel.MEDIUM


class LiteratureAgentOutput(BaseModel):
    evidence: list[LiteratureHit] = Field(default_factory=list)
    summary: str = ""
    contradictions: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class SafetyFlag(BaseModel):
    category: str  # "drug-drug", "drug-disease", "dosing", "population"
    severity: str  # "contraindicated", "major", "moderate", "minor"
    description: str
    mechanism: str = ""
    recommendation: str = ""
    drugs_involved: list[str] = Field(default_factory=list)


class SafetyAgentOutput(BaseModel):
    flags: list[SafetyFlag] = Field(default_factory=list)
    medication_review: str = ""
    dosing_alerts: list[str] = Field(default_factory=list)
    population_warnings: list[str] = Field(default_factory=list)


class CriticOutput(BaseModel):
    ehr_contradictions: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    safety_misses: list[str] = Field(default_factory=list)
    overall_assessment: str = ""
    consensus_reached: bool = False
    dissent_log: list[str] = Field(default_factory=list)


class DebateState(BaseModel):
    """Full state of a debate across rounds."""
    round_number: int = 0
    clinical_outputs: list[ClinicalAgentOutput] = Field(default_factory=list)
    literature_outputs: list[LiteratureAgentOutput] = Field(default_factory=list)
    safety_outputs: list[SafetyAgentOutput] = Field(default_factory=list)
    critic_outputs: list[CriticOutput] = Field(default_factory=list)
    final_consensus: bool = False
    flagged_for_human: bool = False
