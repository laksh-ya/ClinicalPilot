"""
Output Validator — checks SOAP note completeness, safety, and format compliance.
"""

from __future__ import annotations

import logging

from backend.models.soap import SOAPNote, ConfidenceLevel

logger = logging.getLogger(__name__)


def validate_output(soap: SOAPNote) -> SOAPNote:
    """
    Validate and patch the final SOAP output.
    Checks guardrail rules and adds warnings if needed.
    """
    warnings: list[str] = []

    # Rule 1: SOAP sections must not be empty
    if not soap.subjective:
        warnings.append("⚠️ Subjective section is empty")
    if not soap.objective:
        warnings.append("⚠️ Objective section is empty")
    if not soap.assessment:
        warnings.append("⚠️ Assessment section is empty")
    if not soap.plan:
        warnings.append("⚠️ Plan section is empty")

    # Rule 2: Must have ≥2 differentials
    if len(soap.differentials) < 2:
        warnings.append(
            "⚠️ Fewer than 2 differential diagnoses generated. "
            "Clinical reasoning may be incomplete."
        )

    # Rule 3: Safety flags must be explicit
    # (Already included from Safety Agent — just log if missing)
    if not soap.safety_flags:
        logger.info("No safety flags — either no medications or all clear.")

    # Rule 4: Confidence must be set
    if soap.uncertainty == ConfidenceLevel.LOW:
        warnings.append(
            "🔴 LOW confidence case — recommend human review. "
            f"Reason: {soap.uncertainty_reasoning}"
        )

    # Rule 5: Check for potentially hallucinated content
    # (Basic check — real production would cross-reference drug DBs)
    _check_plan_safety(soap, warnings)

    # Add any validation warnings to the dissent log
    if warnings:
        soap.dissent_log = list(set(soap.dissent_log + warnings))

    return soap


def _check_plan_safety(soap: SOAPNote, warnings: list[str]) -> None:
    """Basic checks on the plan section."""
    plan_lower = soap.plan.lower()

    # Check for dangerous instructions without appropriate caveats
    danger_phrases = [
        "discharge home",
        "no follow-up",
        "stop all medications",
    ]
    for phrase in danger_phrases:
        if phrase in plan_lower:
            warnings.append(
                f"⚠️ Plan contains '{phrase}' — verify this is clinically appropriate"
            )
