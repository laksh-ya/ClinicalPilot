"""
SOAP Note models — the primary clinical output of ClinicalPilot.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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


class EmergencyOutput(BaseModel):
    """Fast-path output for Emergency Mode."""

    top_differentials: list[Differential] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    call_to_action: str = ""
    esi_score: Optional[int] = None  # 1-5, 1 = most urgent
    safety_flags: list[str] = Field(default_factory=list)
    latency_ms: int = 0
