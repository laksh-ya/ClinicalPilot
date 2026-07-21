"""
SOAP Note models — the primary clinical output of ClinicalPilot.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .coerce import coerce_confidence, coerce_str_dict, coerce_opt_int, coerce_str, coerce_str_list


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Differential(BaseModel):
    diagnosis: str
    likelihood: str = ""  # e.g. "most likely", "possible", "unlikely"
    reasoning: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    supporting_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare(cls, data):
        # Accept a bare string differential, e.g. "Acute MI"
        if isinstance(data, str):
            return {"diagnosis": data}
        return data

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        return coerce_confidence(v)

    @field_validator("diagnosis", "likelihood", "reasoning", mode="before")
    @classmethod
    def _str(cls, v):
        return coerce_str(v)

    @field_validator("supporting_evidence", mode="before")
    @classmethod
    def _list(cls, v):
        return coerce_str_list(v)


class SOAPNote(BaseModel):
    """Structured SOAP note — the final clinical output."""

    model_config = {"protected_namespaces": ()}

    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""

    differentials: list[Differential] = Field(default_factory=list)

    risk_scores: dict[str, str] = Field(default_factory=dict)
    # e.g. {"HEART Score": "6 — High risk", "Wells PE": "3 — Moderate"}

    uncertainty: ConfidenceLevel = ConfidenceLevel.MEDIUM
    uncertainty_reasoning: str = ""

    citations: list[str] = Field(default_factory=list)

    safety_flags: list[str] = Field(default_factory=list)

    debate_summary: str = ""
    dissent_log: list[str] = Field(default_factory=list)

    # Metadata
    model_used: str = ""
    total_tokens: int = 0
    latency_ms: int = 0

    @field_validator("risk_scores", mode="before")
    @classmethod
    def _risk(cls, v):
        return coerce_str_dict(v)

    @field_validator("uncertainty", mode="before")
    @classmethod
    def _unc(cls, v):
        return coerce_confidence(v)

    @field_validator("subjective", "objective", "assessment", "plan",
                     "uncertainty_reasoning", "debate_summary", mode="before")
    @classmethod
    def _strs(cls, v):
        return coerce_str(v)

    @field_validator("citations", "safety_flags", "dissent_log", mode="before")
    @classmethod
    def _lists(cls, v):
        return coerce_str_list(v)


class EmergencyOutput(BaseModel):
    """Fast-path output for Emergency Mode."""

    top_differentials: list[Differential] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    call_to_action: str = ""
    esi_score: Optional[int] = None  # 1-5, 1 = most urgent
    safety_flags: list[str] = Field(default_factory=list)
    latency_ms: int = 0

    @field_validator("esi_score", mode="before")
    @classmethod
    def _esi(cls, v):
        return coerce_opt_int(v)

    @field_validator("red_flags", "safety_flags", mode="before")
    @classmethod
    def _lists(cls, v):
        return coerce_str_list(v)

    @field_validator("call_to_action", mode="before")
    @classmethod
    def _cta(cls, v):
        return coerce_str(v)
