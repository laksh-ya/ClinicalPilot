"""
Guardrails — output validation rules to prevent hallucinations and ensure quality.
"""

from __future__ import annotations

import logging
import re

from backend.models.soap import SOAPNote

logger = logging.getLogger(__name__)

# Known real drug names (top ~200) for hallucination checking
# In production, this would be the full DrugBank or RxNorm list
KNOWN_DRUG_PREFIXES = {
    "metformin", "lisinopril", "amlodipine", "atorvastatin", "omeprazole",
    "metoprolol", "losartan", "albuterol", "gabapentin", "hydrochlorothiazide",
    "sertraline", "simvastatin", "montelukast", "escitalopram", "rosuvastatin",
    "bupropion", "furosemide", "pantoprazole", "duloxetine", "pravastatin",
    "tamsulosin", "carvedilol", "trazodone", "meloxicam", "clopidogrel",
    "prednisone", "tramadol", "amoxicillin", "azithromycin", "ciprofloxacin",
    "doxycycline", "cephalexin", "clindamycin", "levofloxacin", "warfarin",
    "heparin", "enoxaparin", "rivaroxaban", "apixaban", "aspirin",
    "ibuprofen", "acetaminophen", "naproxen", "morphine", "oxycodone",
    "hydrocodone", "fentanyl", "insulin", "glipizide", "glimepiride",
    "pioglitazone", "sitagliptin", "empagliflozin", "dapagliflozin",
    "liraglutide", "semaglutide", "levothyroxine", "prednisone",
    "methylprednisolone", "dexamethasone", "fluticasone", "budesonide",
    "cetirizine", "loratadine", "diphenhydramine", "ranitidine", "famotidine",
    "diazepam", "lorazepam", "alprazolam", "clonazepam", "zolpidem",
    "quetiapine", "olanzapine", "risperidone", "aripiprazole", "haloperidol",
    "lithium", "valproic", "carbamazepine", "lamotrigine", "levetiracetam",
    "phenytoin", "topiramate", "sumatriptan", "amitriptyline", "nortriptyline",
    "venlafaxine", "fluoxetine", "paroxetine", "citalopram", "mirtazapine",
    "nitroglycerin", "isosorbide", "digoxin", "amiodarone", "diltiazem",
    "verapamil", "nifedipine", "hydralazine", "clonidine", "spironolactone",
    "potassium", "magnesium", "calcium", "iron", "vitamin",
}


def check_soap_guardrails(soap: SOAPNote) -> list[str]:
    """
    Run all guardrail checks on a SOAP note.
    Returns list of warning strings.
    """
    warnings = []
    warnings.extend(_check_completeness(soap))
    warnings.extend(_check_differential_count(soap))
    warnings.extend(_check_safety_explicit(soap))
    warnings.extend(_check_medication_hallucination(soap))
    warnings.extend(_check_confidence_threshold(soap))
    return warnings


def _check_completeness(soap: SOAPNote) -> list[str]:
    """Check SOAP sections are non-empty."""
    issues = []
    for section, label in [
        (soap.subjective, "Subjective"),
        (soap.objective, "Objective"),
        (soap.assessment, "Assessment"),
        (soap.plan, "Plan"),
    ]:
        if not section or len(section.strip()) < 10:
            issues.append(f"GUARDRAIL: {label} section is empty or too short")
    return issues


def _check_differential_count(soap: SOAPNote) -> list[str]:
    """Differential must have ≥2 options."""
    if len(soap.differentials) < 2:
        return [
            "GUARDRAIL: Fewer than 2 differential diagnoses. "
            "Must have at least 2 for clinical completeness."
        ]
    return []


def _check_safety_explicit(soap: SOAPNote) -> list[str]:
    """Safety flags must be explicit if medications are mentioned in the plan."""
    plan_lower = soap.plan.lower()
    has_meds_in_plan = any(
        drug in plan_lower for drug in KNOWN_DRUG_PREFIXES
    )

    if has_meds_in_plan and not soap.safety_flags:
        return [
            "GUARDRAIL: Plan mentions medications but no safety flags were generated. "
            "Safety review may be incomplete."
        ]
    return []


def _check_medication_hallucination(soap: SOAPNote) -> list[str]:
    """Check for potentially hallucinated drug names in the plan."""
    # Extract drug-like words from the plan (capitalized words that look like drugs)
    plan = soap.plan
    # Look for patterns like "Drug 100mg" that aren't in our known list
    drug_patterns = re.findall(
        r"\b([A-Za-z]{4,20})\s+\d+\s*(?:mg|mcg|g|ml|units?)\b",
        plan,
        re.I,
    )
    
    warnings = []
    for drug in drug_patterns:
        drug_lower = drug.lower()
        if not any(drug_lower.startswith(known) or known.startswith(drug_lower) 
                    for known in KNOWN_DRUG_PREFIXES):
            warnings.append(
                f"GUARDRAIL: Drug '{drug}' in plan not found in known drug database. "
                "Verify this is a real medication."
            )
    return warnings


def _check_confidence_threshold(soap: SOAPNote) -> list[str]:
    """Flag low-confidence outputs."""
    from backend.models.soap import ConfidenceLevel

    if soap.uncertainty == ConfidenceLevel.LOW:
        return [
            "GUARDRAIL: Overall confidence is LOW. "
            "Strong recommendation for human clinician review."
        ]
    return []
