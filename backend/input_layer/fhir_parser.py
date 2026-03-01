"""
FHIR Parser — converts HL7 FHIR R4 Bundle JSON into PatientContext.

Supports: Patient, Condition, MedicationRequest, Observation, AllergyIntolerance.
Lightweight: just flattens relevant resources into our unified schema.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.models.patient import (
    Allergy,
    Condition,
    Gender,
    LabResult,
    Medication,
    PatientContext,
    Vital,
)

logger = logging.getLogger(__name__)

# Observation codes that are vitals vs labs
VITAL_CODES = {
    "8310-5": "body_temperature",
    "8867-4": "heart_rate",
    "9279-1": "respiratory_rate",
    "85354-9": "blood_pressure",
    "8480-6": "systolic_bp",
    "8462-4": "diastolic_bp",
    "2708-6": "spo2",
    "29463-7": "body_weight",
    "8302-2": "body_height",
}


def parse_fhir_bundle(bundle: dict) -> PatientContext:
    """Parse a FHIR R4 Bundle and return PatientContext."""
    ctx = PatientContext(source_type="fhir")
    entries = bundle.get("entry", [])

    for entry in entries:
        resource = entry.get("resource", {})
        rtype = resource.get("resourceType", "")

        try:
            if rtype == "Patient":
                _parse_patient(resource, ctx)
            elif rtype == "Condition":
                _parse_condition(resource, ctx)
            elif rtype in ("MedicationRequest", "MedicationStatement"):
                _parse_medication(resource, ctx)
            elif rtype == "Observation":
                _parse_observation(resource, ctx)
            elif rtype == "AllergyIntolerance":
                _parse_allergy(resource, ctx)
        except Exception as e:
            logger.warning(f"Error parsing FHIR {rtype}: {e}")

    # Build raw text summary
    ctx.raw_text = ctx.to_clinical_summary()
    return ctx


def _parse_patient(resource: dict, ctx: PatientContext) -> None:
    """Extract demographics from FHIR Patient resource."""
    # Gender
    gender_str = resource.get("gender", "unknown")
    try:
        ctx.gender = Gender(gender_str)
    except ValueError:
        ctx.gender = Gender.UNKNOWN

    # Age from birthDate
    birth = resource.get("birthDate")
    if birth:
        from datetime import date

        try:
            bd = date.fromisoformat(birth)
            today = date.today()
            ctx.age = today.year - bd.year - (
                (today.month, today.day) < (bd.month, bd.day)
            )
        except Exception:
            pass


def _parse_condition(resource: dict, ctx: PatientContext) -> None:
    """Extract conditions from FHIR Condition resource."""
    code_obj = resource.get("code", {})
    codings = code_obj.get("coding", [])
    display = code_obj.get("text", "")

    if codings:
        c = codings[0]
        code = c.get("code", "")
        display = display or c.get("display", "")
    else:
        code = ""

    onset = resource.get("onsetDateTime", "")
    status = resource.get("clinicalStatus", {})
    status_text = ""
    if isinstance(status, dict):
        codings_s = status.get("coding", [])
        if codings_s:
            status_text = codings_s[0].get("code", "active")

    ctx.conditions.append(
        Condition(code=code, display=display, onset_date=onset, status=status_text or "active")
    )


def _parse_medication(resource: dict, ctx: PatientContext) -> None:
    """Extract medications from FHIR MedicationRequest or MedicationStatement."""
    med_code = resource.get("medicationCodeableConcept", {})
    codings = med_code.get("coding", [])
    name = med_code.get("text", "")
    if codings and not name:
        name = codings[0].get("display", "")

    # Dosage
    dosage_list = resource.get("dosageInstruction", [])
    dose = ""
    freq = ""
    route = "oral"
    if dosage_list:
        d = dosage_list[0]
        dose_quant = d.get("doseAndRate", [{}])[0].get("doseQuantity", {}) if d.get("doseAndRate") else {}
        if dose_quant:
            dose = f"{dose_quant.get('value', '')} {dose_quant.get('unit', '')}".strip()
        timing = d.get("timing", {}).get("code", {}).get("text", "")
        freq = timing
        route = d.get("route", {}).get("text", route)

    status = resource.get("status", "active")
    ctx.medications.append(
        Medication(name=name, dose=dose, frequency=freq, route=route, status=status)
    )


def _parse_observation(resource: dict, ctx: PatientContext) -> None:
    """Extract observations — route to vitals or labs."""
    code_obj = resource.get("code", {})
    codings = code_obj.get("coding", [])
    code = codings[0].get("code", "") if codings else ""
    display = code_obj.get("text", "") or (codings[0].get("display", "") if codings else "")

    # Value
    value_quant = resource.get("valueQuantity", {})
    value_str = resource.get("valueString", "")
    unit = ""
    if value_quant:
        value_str = str(value_quant.get("value", ""))
        unit = value_quant.get("unit", "")

    effective = resource.get("effectiveDateTime", "")

    # Determine if vital or lab
    if code in VITAL_CODES:
        ctx.vitals.append(
            Vital(name=VITAL_CODES.get(code, display), value=value_str, unit=unit, date=effective)
        )
    else:
        # Check for reference range
        ref_range = ""
        ranges = resource.get("referenceRange", [])
        if ranges:
            low = ranges[0].get("low", {}).get("value", "")
            high = ranges[0].get("high", {}).get("value", "")
            if low or high:
                ref_range = f"{low}-{high}"

        interpretation = resource.get("interpretation", [])
        flag = ""
        if interpretation:
            flag_codings = interpretation[0].get("coding", [])
            if flag_codings:
                flag = flag_codings[0].get("code", "")

        ctx.labs.append(
            LabResult(
                name=display,
                value=value_str,
                unit=unit,
                reference_range=ref_range,
                date=effective,
                flag=flag,
            )
        )


def _parse_allergy(resource: dict, ctx: PatientContext) -> None:
    """Extract allergies from FHIR AllergyIntolerance."""
    code_obj = resource.get("code", {})
    substance = code_obj.get("text", "")
    if not substance:
        codings = code_obj.get("coding", [])
        if codings:
            substance = codings[0].get("display", "")

    reactions = resource.get("reaction", [])
    reaction_str = ""
    severity = ""
    if reactions:
        manifestations = reactions[0].get("manifestation", [])
        if manifestations:
            reaction_str = manifestations[0].get("coding", [{}])[0].get("display", "")
        severity = reactions[0].get("severity", "")

    ctx.allergies.append(
        Allergy(substance=substance, reaction=reaction_str, severity=severity)
    )
