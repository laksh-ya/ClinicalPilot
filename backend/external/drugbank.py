"""
DrugBank Open Data — lookups for drug names and known interactions.

Expects: data/drugbank/drugbank_vocabulary.csv
Download from: https://go.drugbank.com/releases/latest#open-data
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

from backend.config import get_settings

logger = logging.getLogger(__name__)

# In-memory cache
_drug_db: Optional[dict[str, dict]] = None


def _load_drugbank() -> dict[str, dict]:
    """Load DrugBank vocabulary CSV into memory."""
    global _drug_db
    if _drug_db is not None:
        return _drug_db

    settings = get_settings()
    csv_path = settings.drugbank_abs_path

    if not csv_path.exists():
        logger.warning(f"DrugBank CSV not found at {csv_path}")
        _drug_db = {}
        return _drug_db

    _drug_db = {}
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                drugbank_id = row.get("DrugBank ID", "")
                name = row.get("Common name", "").lower()
                if name:
                    _drug_db[name] = {
                        "id": drugbank_id,
                        "name": row.get("Common name", ""),
                        "cas": row.get("CAS", ""),
                        "unii": row.get("UNII", ""),
                        "synonyms": row.get("Synonyms", ""),
                    }
        logger.info(f"Loaded {len(_drug_db)} drugs from DrugBank")
    except Exception as e:
        logger.error(f"Failed to load DrugBank: {e}")
        _drug_db = {}

    return _drug_db


def lookup_drug(name: str) -> Optional[dict]:
    """Look up a drug by name in DrugBank."""
    db = _load_drugbank()
    return db.get(name.lower())


def lookup_interactions(drug_names: list[str]) -> str:
    """
    Look up known interactions for a list of drugs.
    Returns formatted string (the open DrugBank data doesn't include interactions,
    but we can at least validate drug names and flag unrecognized drugs).
    """
    db = _load_drugbank()
    if not db:
        return ""

    results = []
    for name in drug_names:
        drug = db.get(name.lower())
        if drug:
            results.append(f"✓ {drug['name']} (DrugBank: {drug['id']})")
        else:
            # Try partial match
            matches = [
                v for k, v in db.items()
                if name.lower() in k or k in name.lower()
            ]
            if matches:
                results.append(
                    f"~ {name} → possible match: {matches[0]['name']} ({matches[0]['id']})"
                )
            else:
                results.append(f"✗ {name} — not found in DrugBank (verify drug name)")

    return "\n".join(results)
