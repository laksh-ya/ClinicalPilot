"""
Literature Agent — searches PubMed and RAG for relevant evidence.
Uses GPT-4o-mini for speed.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import get_settings
from backend.models.patient import PatientContext
from backend.models.agents import LiteratureAgentOutput, LiteratureHit, ClinicalAgentOutput
from backend.models.soap import ConfidenceLevel
from .llm_client import llm_call, load_prompt

logger = logging.getLogger(__name__)


async def run_literature_agent(
    patient: PatientContext,
    clinical_output: ClinicalAgentOutput | None = None,
    critique: str = "",
) -> LiteratureAgentOutput:
    """
    Run the Literature Agent — searches for relevant medical evidence.
    
    Args:
        patient: Unified patient context
        clinical_output: Optional output from Clinical Agent (to search for evidence)
        critique: Optional critique from previous debate round
    """
    settings = get_settings()
    system_prompt = load_prompt("literature_system.txt")

    user_message = f"""## Patient Context
{patient.to_clinical_summary()}
"""

    if clinical_output:
        ddx_list = "\n".join(
            f"- {d.diagnosis} ({d.likelihood})" for d in clinical_output.differentials
        )
        user_message += f"""
## Differential Diagnoses to Research
{ddx_list}

## Clinical Agent's Reasoning
{clinical_output.reasoning_trace}
"""

    # Try PubMed search for real evidence
    pubmed_results = await _search_pubmed(patient, clinical_output)
    if pubmed_results:
        user_message += f"""
## PubMed Search Results (real citations)
{pubmed_results}
"""

    if critique:
        user_message += f"""
## Critique from Previous Round (address these issues)
{critique}
"""

    result = await llm_call(
        system_prompt=system_prompt,
        user_message=user_message,
        model=settings.openai_fast_model,  # Use fast model for literature
        json_mode=True,
    )

    return _parse_output(result["content"])


async def _search_pubmed(
    patient: PatientContext,
    clinical_output: ClinicalAgentOutput | None,
) -> str:
    """Search PubMed for relevant papers. Returns formatted string."""
    try:
        from backend.external.pubmed import search_pubmed

        # Build search query from top differentials
        queries = []
        if clinical_output and clinical_output.differentials:
            for d in clinical_output.differentials[:3]:
                queries.append(d.diagnosis)

        # Also search for the primary condition
        if patient.conditions:
            queries.extend(c.display for c in patient.conditions[:2])

        if not queries:
            queries = [patient.current_prompt[:100]]

        results = []
        # Run all PubMed searches in parallel
        import asyncio
        tasks = [search_pubmed(q, max_results=3) for q in queries[:3]]
        all_hits = await asyncio.gather(*tasks, return_exceptions=True)
        for hits in all_hits:
            if isinstance(hits, list):
                results.extend(hits)

        if not results:
            return ""

        formatted = []
        for r in results[:8]:  # Max 8 results
            formatted.append(
                f"- [{r.get('title', 'No title')}] "
                f"({r.get('journal', '')}, {r.get('year', '')}). "
                f"PMID: {r.get('pmid', 'N/A')}. "
                f"{r.get('abstract', '')[:200]}..."
            )
        return "\n".join(formatted)

    except Exception as e:
        logger.warning(f"PubMed search failed: {e}")
        return ""


def _parse_output(data: Any) -> LiteratureAgentOutput:
    """Parse LLM JSON response into typed output."""
    if isinstance(data, str):
        return LiteratureAgentOutput(summary=data)

    evidence = []
    for e in data.get("evidence", []):
        evidence.append(
            LiteratureHit(
                title=e.get("title", ""),
                authors=e.get("authors", ""),
                journal=e.get("journal", ""),
                year=e.get("year", ""),
                pmid=e.get("pmid", ""),
                snippet=e.get("snippet", ""),
                relevance=_parse_confidence(e.get("relevance", "medium")),
            )
        )

    return LiteratureAgentOutput(
        evidence=evidence,
        summary=data.get("summary", ""),
        contradictions=data.get("contradictions", []),
        confidence=_parse_confidence(data.get("confidence", "medium")),
    )


def _parse_confidence(val: str) -> ConfidenceLevel:
    try:
        return ConfidenceLevel(val.lower())
    except (ValueError, AttributeError):
        return ConfidenceLevel.MEDIUM
