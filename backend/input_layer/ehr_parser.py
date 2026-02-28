"""
EHR Parser — handles PDF and CSV uploads, extracts clinical data.

Uses PyPDF2 for basic PDF text extraction.
Falls back gracefully if unstructured is not installed.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path
from typing import Optional

from backend.models.patient import (
    Condition,
    Gender,
    LabResult,
    Medication,
    PatientContext,
    Vital,
)

logger = logging.getLogger(__name__)


async def parse_ehr_pdf(file_bytes: bytes, filename: str = "") -> PatientContext:
    """Extract text from a PDF and build PatientContext."""
    text = _extract_pdf_text(file_bytes)
    ctx = _extract_clinical_entities(text)
    ctx.source_type = "ehr_pdf"
    ctx.raw_text = text
    return ctx


async def parse_ehr_csv(file_bytes: bytes, filename: str = "") -> PatientContext:
    """Parse a CSV file with clinical data columns."""
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    ctx = PatientContext(source_type="ehr_csv")

    for row in reader:
        # Try common column names
        row_lower = {k.lower().strip(): v for k, v in row.items()}

        # Demographics
        if "age" in row_lower and row_lower["age"]:
            try:
                ctx.age = int(row_lower["age"])
            except ValueError:
                pass

        if "gender" in row_lower or "sex" in row_lower:
            g = row_lower.get("gender", row_lower.get("sex", "")).lower()
            if "male" in g and "female" not in g:
                ctx.gender = Gender.MALE
            elif "female" in g:
                ctx.gender = Gender.FEMALE

        # Conditions
        for key in ("diagnosis", "condition", "problem", "dx"):
            if key in row_lower and row_lower[key]:
                ctx.conditions.append(Condition(display=row_lower[key]))

        # Medications
        for key in ("medication", "drug", "med", "rx"):
            if key in row_lower and row_lower[key]:
                dose = row_lower.get("dose", row_lower.get("dosage", ""))
                freq = row_lower.get("frequency", row_lower.get("freq", ""))
                ctx.medications.append(
                    Medication(name=row_lower[key], dose=dose, frequency=freq)
                )

        # Labs
        for key in ("lab", "test", "lab_name"):
            if key in row_lower and row_lower[key]:
                val = row_lower.get("value", row_lower.get("result", ""))
                unit = row_lower.get("unit", row_lower.get("units", ""))
                ctx.labs.append(LabResult(name=row_lower[key], value=val, unit=unit))

    ctx.raw_text = text[:5000]  # Keep first 5k chars
    return ctx


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF using PyPDF2 (or unstructured as fallback)."""
    # Try unstructured first
    try:
        from unstructured.partition.pdf import partition_pdf

        elements = partition_pdf(file=io.BytesIO(file_bytes))
        return "\n".join(str(e) for e in elements)
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Unstructured PDF parsing failed: {e}")

    # Fallback to PyPDF2
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        logger.error(f"PDF parsing failed: {e}")
        return ""


def _extract_clinical_entities(text: str) -> PatientContext:
    """
    Simple regex + heuristic extraction from free-text EHR documents.
    This is a best-effort parser for unstructured clinical text.
    """
    ctx = PatientContext()

    # Age
    age_match = re.search(r"(\d{1,3})[\s-]*(?:year|yr|y/?o|y\.o\.)", text, re.I)
    if age_match:
        ctx.age = int(age_match.group(1))

    # Gender
    if re.search(r"\b(?:male|man|gentleman)\b", text, re.I):
        ctx.gender = Gender.MALE
    elif re.search(r"\b(?:female|woman|lady)\b", text, re.I):
        ctx.gender = Gender.FEMALE

    # Medications — look for common patterns
    med_section = re.search(
        r"(?:medications?|meds|current\s+medications?)[:\s]*(.*?)(?:\n\n|\n[A-Z])",
        text,
        re.I | re.S,
    )
    if med_section:
        med_text = med_section.group(1)
        for line in med_text.split("\n"):
            line = line.strip().strip("-•*")
            if line and len(line) > 2:
                ctx.medications.append(Medication(name=line))

    # Conditions — look for common patterns
    for pattern in [
        r"(?:history\s+of|h/o|pmh|past\s+medical)[:\s]*(.*?)(?:\n\n|\n[A-Z])",
        r"(?:diagnos[ei]s|assessment)[:\s]*(.*?)(?:\n\n|\n[A-Z])",
    ]:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            for line in match.group(1).split("\n"):
                line = line.strip().strip("-•*1234567890.")
                if line and len(line) > 2:
                    ctx.conditions.append(Condition(display=line))

    return ctx
