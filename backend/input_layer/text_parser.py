"""
Text Parser — converts free text or voice transcription into PatientContext.
Extracts demographics, conditions, medications, vitals, labs, and allergies using heuristics.
"""

from __future__ import annotations

import re

from backend.models.patient import (
    Allergy,
    Condition,
    Gender,
    LabResult,
    Medication,
    PatientContext,
    Vital,
)


def parse_text_input(text: str) -> PatientContext:
    """
    Parse free text clinical input into PatientContext.
    Extracts demographics, conditions, medications, vitals, labs, and allergies.
    """
    ctx = PatientContext(
        source_type="text",
        current_prompt=text,
        raw_text=text,
    )

    _extract_demographics(text, ctx)
    _extract_medications(text, ctx)
    _extract_conditions(text, ctx)
    _extract_vitals(text, ctx)
    _extract_labs(text, ctx)
    _extract_allergies(text, ctx)

    return ctx


def _extract_demographics(text: str, ctx: PatientContext) -> None:
    """Extract age and gender from text."""
    age_match = re.search(
        r"(\d{1,3})[\s-]*(?:year|yr|y/?o|y\.o\.|year[\s-]*old)", text, re.I
    )
    if age_match:
        ctx.age = int(age_match.group(1))

    text_lower = text.lower()
    if re.search(r"\b(?:female|woman|lady|girl|she|her)\b", text_lower):
        ctx.gender = Gender.FEMALE
    elif re.search(r"\b(?:male|man|gentleman|boy|he|his)\b", text_lower):
        ctx.gender = Gender.MALE


def _extract_medications(text: str, ctx: PatientContext) -> None:
    """Extract medications from text."""
    # Pattern: drug_name dose frequency
    med_patterns = [
        r"(\b[a-zA-Z]{4,20})\s+(\d+\s*(?:mg|mcg|g|ml|units?))\s*((?:BID|TID|QID|daily|once|twice|PRN|q\d+h?|at bedtime|QHS)?)",
        r"(\b[a-zA-Z]{4,20})\s+(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?)\s*((?:BID|TID|QID|daily|once|twice|PRN|q\d+h?)?)",
    ]

    skip_words = {
        "with", "from", "have", "that", "this", "been", "year",
        "type", "about", "over", "under", "after", "before",
        "presenting", "patient", "history", "taking",
    }

    found_meds = set()
    for pattern in med_patterns:
        for match in re.finditer(pattern, text, re.I):
            name = match.group(1).strip()
            if name.lower() in skip_words:
                continue
            if name.lower() not in found_meds:
                found_meds.add(name.lower())
                dose = match.group(2).strip() if len(match.groups()) >= 2 else ""
                freq = match.group(3).strip() if len(match.groups()) >= 3 else ""
                ctx.medications.append(
                    Medication(name=name, dose=dose, frequency=freq)
                )

    # Also look for medication section
    med_section = re.search(
        r"(?:current\s+)?medications?[:\s]+(.*?)(?:\.\s*[A-Z]|\n\n|$)",
        text,
        re.I | re.S,
    )
    if med_section:
        section_text = med_section.group(1)
        for item in re.split(r"[,;]|\band\b", section_text):
            item = item.strip().strip(".-•")
            if item and len(item) > 2:
                if not any(item.lower().startswith(m.name.lower()) for m in ctx.medications):
                    # Try to separate drug name from dose/frequency
                    med_parse = re.match(
                        r"^([a-zA-Z][a-zA-Z\s-]{2,})\s+(\d+\s*(?:mg|mcg|g|ml|mEq|units?)(?:/\w+)?)\s*(.*?)$",
                        item, re.I,
                    )
                    if med_parse:
                        ctx.medications.append(Medication(
                            name=med_parse.group(1).strip(),
                            dose=med_parse.group(2).strip(),
                            frequency=med_parse.group(3).strip(),
                        ))
                    else:
                        ctx.medications.append(Medication(name=item))


def _extract_conditions(text: str, ctx: PatientContext) -> None:
    """Extract conditions/diagnoses from text."""
    condition_map = {
        r"\bHTN\b": "Hypertension",
        r"\bDM\s*2?\b|\bT2DM\b|\btype\s*2\s*diabetes\b": "Type 2 Diabetes Mellitus",
        r"\bDM\s*1\b|\bT1DM\b|\btype\s*1\s*diabetes\b": "Type 1 Diabetes Mellitus",
        r"\bCAD\b": "Coronary Artery Disease",
        r"\bCHF\b|\bheart\s+failure\b": "Congestive Heart Failure",
        r"\bCOPD\b": "Chronic Obstructive Pulmonary Disease",
        r"\bCKD\b": "Chronic Kidney Disease",
        r"\bAF\b|\bAfib\b|\batrial\s+fib": "Atrial Fibrillation",
        r"\bPE\b(?!\s*exam)": "Pulmonary Embolism",
        r"\bDVT\b": "Deep Vein Thrombosis",
        r"\bMI\b|\bmyocardial\s+infarction\b": "Myocardial Infarction",
        r"\bCVA\b|\bstroke\b": "Cerebrovascular Accident",
        r"\basthma\b": "Asthma",
        r"\bGERD\b": "Gastroesophageal Reflux Disease",
        r"\bhyperlipidemia\b|\bhigh\s+cholesterol\b": "Hyperlipidemia",
        r"\bhypothyroid": "Hypothyroidism",
        r"\banxiety\b": "Anxiety Disorder",
        r"\bdepression\b": "Major Depressive Disorder",
        r"\bobesity\b|\bBMI\s*>\s*30\b": "Obesity",
    }

    for pattern, display in condition_map.items():
        if re.search(pattern, text, re.I):
            if not any(c.display == display for c in ctx.conditions):
                ctx.conditions.append(Condition(display=display))

    for match in re.finditer(
        r"(?:history\s+of|h/o|diagnosed\s+with|known)\s+([\w\s]{3,40}?)(?:[,.\n;]|$)",
        text,
        re.I,
    ):
        cond = match.group(1).strip()
        if cond and not any(c.display.lower() == cond.lower() for c in ctx.conditions):
            ctx.conditions.append(Condition(display=cond))


def _extract_vitals(text: str, ctx: PatientContext) -> None:
    """Extract vital signs from text."""
    bp_match = re.search(r"BP[:\s]*(\d{2,3})/(\d{2,3})", text, re.I)
    if bp_match:
        ctx.vitals.append(
            Vital(name="blood_pressure", value=f"{bp_match.group(1)}/{bp_match.group(2)}", unit="mmHg")
        )

    hr_match = re.search(r"(?:HR|heart\s*rate|pulse)[:\s]*(\d{2,3})", text, re.I)
    if hr_match:
        ctx.vitals.append(Vital(name="heart_rate", value=hr_match.group(1), unit="bpm"))

    rr_match = re.search(r"(?:RR|resp(?:iratory)?\s*rate)[:\s]*(\d{1,2})", text, re.I)
    if rr_match:
        ctx.vitals.append(Vital(name="respiratory_rate", value=rr_match.group(1), unit="/min"))

    temp_match = re.search(r"(?:temp|temperature)[:\s]*([\d.]+)\s*°?\s*([FC])?", text, re.I)
    if temp_match:
        unit = "°" + (temp_match.group(2) or "F")
        ctx.vitals.append(Vital(name="temperature", value=temp_match.group(1), unit=unit))

    spo2_match = re.search(r"(?:SpO2|O2\s*sat|oxygen\s*sat)[:\s]*(\d{2,3})%?", text, re.I)
    if spo2_match:
        ctx.vitals.append(Vital(name="spo2", value=spo2_match.group(1), unit="%"))


def _extract_labs(text: str, ctx: PatientContext) -> None:
    """Extract lab values from text."""
    lab_patterns = {
        r"troponin[:\s]*([\d.]+)\s*(ng/mL|ng/dL|μg/L)?": ("Troponin", "ng/mL"),
        r"(?:WBC|white\s*(?:blood\s*)?count)[:\s]*([\d.]+)\s*(K/μL|×10³)?": ("WBC", "K/μL"),
        r"(?:Hgb|hemoglobin)[:\s]*([\d.]+)\s*(g/dL)?": ("Hemoglobin", "g/dL"),
        r"creatinine[:\s]*([\d.]+)\s*(mg/dL)?": ("Creatinine", "mg/dL"),
        r"(?:BUN|blood\s*urea\s*nitrogen)[:\s]*([\d.]+)\s*(mg/dL)?": ("BUN", "mg/dL"),
        r"(?:eGFR|GFR)[:\s]*([\d.]+)": ("eGFR", "mL/min"),
        r"glucose[:\s]*([\d.]+)\s*(mg/dL)?": ("Glucose", "mg/dL"),
        r"(?:HbA1c|A1C)[:\s]*([\d.]+)%?": ("HbA1c", "%"),
        r"(?:Na|sodium)[:\s]*([\d.]+)\s*(mEq/L|mmol/L)?": ("Sodium", "mEq/L"),
        r"(?:K\+?|potassium)[:\s]*([\d.]+)\s*(mEq/L|mmol/L)?": ("Potassium", "mEq/L"),
        r"D-?dimer[:\s]*([\d.]+)\s*(ng/mL|μg/mL)?": ("D-dimer", "ng/mL"),
        r"(?:BNP|NT-proBNP)[:\s]*([\d.]+)\s*(pg/mL)?": ("BNP", "pg/mL"),
        r"lactate[:\s]*([\d.]+)\s*(mmol/L)?": ("Lactate", "mmol/L"),
    }

    for pattern, (name, default_unit) in lab_patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(1)
            unit = match.group(2) if len(match.groups()) >= 2 and match.group(2) else default_unit
            ctx.labs.append(LabResult(name=name, value=value, unit=unit))


def _extract_allergies(text: str, ctx: PatientContext) -> None:
    """Extract allergies from text."""
    if re.search(r"\bNKDA\b|\bno\s+known\s+(?:drug\s+)?allergies\b", text, re.I):
        return

    allergy_match = re.search(
        r"(?:allerg(?:y|ic|ies)\s*(?:to|:)\s*)([\w\s,]+?)(?:\.\s|$|\n)",
        text,
        re.I,
    )
    if allergy_match:
        for item in re.split(r"[,;]\s*|\band\b", allergy_match.group(1)):
            item = item.strip()
            if item and len(item) > 1:
                ctx.allergies.append(Allergy(substance=item))
