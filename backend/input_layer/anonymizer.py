"""
PHI Anonymizer — uses Microsoft Presidio to scrub protected health information
while preserving clinical meaning.

Falls back to regex-based scrubbing if Presidio is not installed.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import Presidio; graceful fallback if not installed
_PRESIDIO_AVAILABLE = False
try:
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig

    _PRESIDIO_AVAILABLE = True
except ImportError:
    logger.warning(
        "Presidio not installed — falling back to regex-based anonymization. "
        "Install with: pip install presidio-analyzer presidio-anonymizer spacy && "
        "python -m spacy download en_core_web_lg"
    )


class Anonymizer:
    """Scrubs PHI from clinical text."""

    def __init__(self, spacy_model: str = "en_core_web_lg"):
        self._presidio_analyzer: Optional[AnalyzerEngine] = None
        self._presidio_anonymizer: Optional[AnonymizerEngine] = None

        if _PRESIDIO_AVAILABLE:
            try:
                # Ensure spaCy model is available
                import spacy
                try:
                    spacy.load(spacy_model)
                except OSError:
                    logger.info(f"Downloading spaCy model {spacy_model}...")
                    import subprocess, sys
                    subprocess.check_call(
                        [sys.executable, "-m", "spacy", "download", spacy_model],
                    )
                    # Verify it loaded after download
                    spacy.load(spacy_model)

                from presidio_analyzer.nlp_engine import (
                    NlpEngineProvider,
                )

                provider = NlpEngineProvider(
                    nlp_configuration={
                        "nlp_engine_name": "spacy",
                        "models": [{"lang_code": "en", "model_name": spacy_model}],
                    }
                )
                nlp_engine = provider.create_engine()

                registry = RecognizerRegistry()
                registry.load_predefined_recognizers(nlp_engine=nlp_engine)

                self._presidio_analyzer = AnalyzerEngine(
                    nlp_engine=nlp_engine, registry=registry
                )
                self._presidio_anonymizer = AnonymizerEngine()
                logger.info("Presidio anonymizer initialized successfully.")
            except Exception as e:
                logger.warning(f"Presidio init failed ({e}); using regex fallback.")
                self._presidio_analyzer = None

    def anonymize(self, text: str) -> str:
        """Remove PHI from text, preserving clinical content."""
        if not text:
            return text

        if self._presidio_analyzer and self._presidio_anonymizer:
            return self._anonymize_presidio(text)
        return self._anonymize_regex(text)

    def _anonymize_presidio(self, text: str) -> str:
        """Presidio-based anonymization.
        
        NOTE: We intentionally EXCLUDE DATE_TIME from Presidio entities
        because it causes false positives on medication dosages (e.g. '20mEq'
        gets misidentified as a date). We handle date anonymization via
        post-processing regex instead, which is more targeted.
        """
        entities = [
            "PERSON",
            "PHONE_NUMBER",
            "EMAIL_ADDRESS",
            "US_SSN",
            "CREDIT_CARD",
            "IP_ADDRESS",
            # "DATE_TIME",  # EXCLUDED: causes false positives on med dosages
            "LOCATION",
            "US_DRIVER_LICENSE",
            "MEDICAL_LICENSE",
            "URL",
        ]
        results = self._presidio_analyzer.analyze(
            text=text, entities=entities, language="en"
        )

        # Filter out LOCATION entities that look like clinical terms
        # (Presidio sometimes flags drug names or body parts as locations)
        clinical_terms = {
            "oral", "iv", "im", "sq", "topical", "rectal", "nasal",
            "left", "right", "bilateral", "chest", "abdomen", "head",
        }
        results = [
            r for r in results
            if not (
                r.entity_type == "LOCATION"
                and text[r.start:r.end].strip().lower() in clinical_terms
            )
        ]

        anonymized = self._presidio_anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators={
                "PERSON": OperatorConfig("replace", {"new_value": "[PATIENT]"}),
                "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE]"}),
                "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}),
                "US_SSN": OperatorConfig("replace", {"new_value": "[SSN]"}),
                "LOCATION": OperatorConfig("replace", {"new_value": "[LOCATION]"}),
                "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            },
        )

        # Post-process: scrub date-of-birth patterns via regex
        # (targeted to DOB-like formats, avoiding clinical dates like onset dates)
        result = anonymized.text
        result = re.sub(
            r"\b(?:DOB|Date of Birth|Birth\s?date)[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
            "[DOB REDACTED]",
            result,
            flags=re.I,
        )
        return result

    def _anonymize_regex(self, text: str) -> str:
        """Regex fallback — catches common PHI patterns."""
        # SSN
        text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]", text)
        # Phone numbers
        text = re.sub(
            r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            "[PHONE]",
            text,
        )
        # Email
        text = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", "[EMAIL]", text)
        # Dates (MM/DD/YYYY, YYYY-MM-DD, etc.) -- be careful not to remove clinical dates
        text = re.sub(
            r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "[DATE]", text
        )
        # MRN patterns (common: MRN: 123456)
        text = re.sub(r"\bMRN[:\s]*\d+\b", "MRN: [REDACTED]", text, flags=re.I)
        return text


# Module-level singleton (lazy init)
_anonymizer: Optional[Anonymizer] = None


def get_anonymizer(spacy_model: str = "en_core_web_lg") -> Anonymizer:
    global _anonymizer
    if _anonymizer is None:
        _anonymizer = Anonymizer(spacy_model=spacy_model)
    return _anonymizer
