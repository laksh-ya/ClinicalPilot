"""
Observability — LangSmith / Langfuse integration for tracing.
Set LANGCHAIN_TRACING_V2=true and LANGSMITH_API_KEY in .env to enable.
"""

from __future__ import annotations

import logging
import os

from backend.config import get_settings

logger = logging.getLogger(__name__)


def setup_tracing() -> bool:
    """
    Configure LangSmith tracing if environment is set up.
    Call this once at app startup.
    
    Returns True if tracing is enabled.
    """
    settings = get_settings()

    if not settings.langchain_tracing_v2:
        logger.info("LangSmith tracing is disabled (LANGCHAIN_TRACING_V2=false)")
        return False

    if not settings.langsmith_api_key:
        logger.warning("LANGSMITH_API_KEY not set — tracing disabled")
        return False

    # Set environment variables that LangChain/LangSmith SDK reads
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project

    logger.info(f"LangSmith tracing enabled for project: {settings.langchain_project}")
    return True


def get_tracing_status() -> dict:
    """Return current tracing configuration status."""
    settings = get_settings()
    return {
        "enabled": settings.langchain_tracing_v2 and bool(settings.langsmith_api_key),
        "project": settings.langchain_project,
        "provider": "langsmith",
    }
