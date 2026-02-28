"""
RxNorm API — drug normalization and interaction checking via NLM API.
Free, no API key required.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"


async def get_rxcui(drug_name: str) -> Optional[str]:
    """Get RxNorm CUI for a drug name."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{RXNORM_BASE}/rxcui.json",
                params={"name": drug_name, "search": 2},
            )
            resp.raise_for_status()
            data = resp.json()
            ids = data.get("idGroup", {}).get("rxnormId", [])
            return ids[0] if ids else None
    except Exception as e:
        logger.debug(f"RxNorm lookup failed for {drug_name}: {e}")
        return None


async def check_interactions_rxnorm(drug_names: list[str]) -> list[dict]:
    """
    Check drug-drug interactions using RxNorm interaction API.
    
    Returns list of interaction dicts.
    """
    # First, get RxCUIs for all drugs in parallel
    import asyncio
    cui_results = await asyncio.gather(*[get_rxcui(name) for name in drug_names])
    rxcuis = [cui for cui in cui_results if cui]

    if len(rxcuis) < 2:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{RXNORM_BASE}/interaction/list.json",
                params={"rxcuis": "+".join(rxcuis)},
            )
            resp.raise_for_status()
            data = resp.json()

        interactions = []
        for group in data.get("fullInteractionTypeGroup", []):
            for itype in group.get("fullInteractionType", []):
                for pair in itype.get("interactionPair", []):
                    desc = pair.get("description", "")
                    severity = pair.get("severity", "N/A")
                    concepts = pair.get("interactionConcept", [])
                    names = [
                        c.get("minConceptItem", {}).get("name", "")
                        for c in concepts
                    ]
                    interactions.append({
                        "drugs": names,
                        "description": desc,
                        "severity": severity,
                    })

        return interactions

    except Exception as e:
        logger.warning(f"RxNorm interaction check failed: {e}")
        return []
