"""
Agent input / output models — used by orchestrator and debate layer.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .soap import ConfidenceLevel, Differential
from .coerce import coerce_confidence, coerce_str_dict, coerce_str, coerce_str_list, coerce_bool


class ClinicalAgentOutput(BaseModel):
    differentials: list[Differential] = Field(default_factory=list)
    risk_scores: dict[str, str] = Field(default_factory=dict)
    soap_draft: str = ""
    reasoning_trace: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM

    @field_validator("risk_scores", mode="before")
    @classmethod
    def _risk(cls, v):
        return coerce_str_dict(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        return coerce_confidence(v)

    @field_validator("soap_draft", "reasoning_trace", mode="before")
    @classmethod
    def _str(cls, v):
        return coerce_str(v)


class LiteratureHit(BaseModel):
    title: str
    authors: str = ""
    journal: str = ""
    year: str = ""
    pmid: str = ""
    snippet: str = ""
    relevance: ConfidenceLevel = ConfidenceLevel.MEDIUM

    @field_validator("relevance", mode="before")
    @classmethod
    def _rel(cls, v):
        return coerce_confidence(v)

    @field_validator("title", "authors", "journal", "year", "pmid", "snippet", mode="before")
    @classmethod
    def _str(cls, v):
        return coerce_str(v)


class LiteratureAgentOutput(BaseModel):
    evidence: list[LiteratureHit] = Field(default_factory=list)
    summary: str = ""
    contradictions: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        return coerce_confidence(v)

    @field_validator("summary", mode="before")
    @classmethod
    def _str(cls, v):
        return coerce_str(v)

    @field_validator("contradictions", mode="before")
    @classmethod
    def _list(cls, v):
        return coerce_str_list(v)


class SafetyFlag(BaseModel):
    category: str  # "drug-drug", "drug-disease", "dosing", "population"
    severity: str  # "contraindicated", "major", "moderate", "minor"
    description: str
    mechanism: str = ""
    recommendation: str = ""
    drugs_involved: list[str] = Field(default_factory=list)

    @field_validator("category", "severity", "description", "mechanism", "recommendation", mode="before")
    @classmethod
    def _str(cls, v):
        return coerce_str(v)

    @field_validator("drugs_involved", mode="before")
    @classmethod
    def _list(cls, v):
        return coerce_str_list(v)


class SafetyAgentOutput(BaseModel):
    flags: list[SafetyFlag] = Field(default_factory=list)
    medication_review: str = ""
    dosing_alerts: list[str] = Field(default_factory=list)
    population_warnings: list[str] = Field(default_factory=list)

    @field_validator("medication_review", mode="before")
    @classmethod
    def _str(cls, v):
        return coerce_str(v)

    @field_validator("dosing_alerts", "population_warnings", mode="before")
    @classmethod
    def _lists(cls, v):
        return coerce_str_list(v)


class CriticOutput(BaseModel):
    ehr_contradictions: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    safety_misses: list[str] = Field(default_factory=list)
    overall_assessment: str = ""
    consensus_reached: bool = False
    dissent_log: list[str] = Field(default_factory=list)

    @field_validator("consensus_reached", mode="before")
    @classmethod
    def _bool(cls, v):
        return coerce_bool(v)

    @field_validator("overall_assessment", mode="before")
    @classmethod
    def _str(cls, v):
        return coerce_str(v)

    @field_validator("ehr_contradictions", "evidence_gaps", "safety_misses", "dissent_log", mode="before")
    @classmethod
    def _lists(cls, v):
        return coerce_str_list(v)


class DebateState(BaseModel):
    """Full state of a debate across rounds."""
    round_number: int = 0
    clinical_outputs: list[ClinicalAgentOutput] = Field(default_factory=list)
    literature_outputs: list[LiteratureAgentOutput] = Field(default_factory=list)
    safety_outputs: list[SafetyAgentOutput] = Field(default_factory=list)
    critic_outputs: list[CriticOutput] = Field(default_factory=list)
    final_consensus: bool = False
    flagged_for_human: bool = False
