"""
FDA openFDA API — drug label lookups and adverse event data.
Free API, works without key (lower rate limits).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)

FDA_BASE = "https://api.fda.gov"


async def check_drug_interactions(drug_names: list[str]) -> str:
    """
    Check openFDA for drug label warnings related to interactions.
    Returns formatted string of findings.
    """
    if not drug_names:
        return ""

    import asyncio

    async def _lookup(name: str) -> tuple[str, str]:
        try:
            data = await _search_drug_label(name)
            return name, data
        except Exception as e:
            logger.debug(f"FDA lookup failed for {name}: {e}")
            return name, ""

    # Run all lookups in parallel
    pairs = await asyncio.gather(*[_lookup(n) for n in drug_names[:5]])
    results = [f"**{name}**: {data}" for name, data in pairs if data]
    return "\n".join(results) if results else ""


async def _search_drug_label(drug_name: str) -> str:
    """Search openFDA drug labels for warnings and interactions."""
    settings = get_settings()

    params: dict[str, Any] = {
        "search": f'openfda.generic_name:"{drug_name}"',
        "limit": 1,
    }
    if settings.fda_api_key:
        params["api_key"] = settings.fda_api_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{FDA_BASE}/drug/label.json", params=params)

            if resp.status_code == 404:
                return ""

            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return ""

        label = results[0]
        parts = []

        # Drug interactions section
        interactions = label.get("drug_interactions", [])
        if interactions:
            parts.append(f"Interactions: {interactions[0][:300]}")

        # Warnings section
        warnings = label.get("warnings", [])
        if warnings:
            parts.append(f"Warnings: {warnings[0][:300]}")

        # Contraindications
        contras = label.get("contraindications", [])
        if contras:
            parts.append(f"Contraindications: {contras[0][:300]}")

        return " | ".join(parts) if parts else ""

    except Exception as e:
        logger.debug(f"FDA API request failed: {e}")
        return ""


async def search_adverse_events(drug_name: str, limit: int = 5) -> list[dict]:
    """Search openFDA adverse event reports for a drug."""
    settings = get_settings()

    params: dict[str, Any] = {
        "search": f'patient.drug.medicinalproduct:"{drug_name}"',
        "limit": limit,
    }
    if settings.fda_api_key:
        params["api_key"] = settings.fda_api_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{FDA_BASE}/drug/event.json", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
    except Exception as e:
        logger.debug(f"FDA adverse events search failed: {e}")
        return []
