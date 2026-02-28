"""
PubMed Search — uses NCBI E-utilities (BioPython Entrez) to search for medical literature.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import get_settings

logger = logging.getLogger(__name__)


async def search_pubmed(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """
    Search PubMed for relevant articles.
    
    Returns list of dicts with: title, authors, journal, year, pmid, abstract
    """
    settings = get_settings()

    if not settings.ncbi_email:
        logger.warning("NCBI_EMAIL not set — PubMed search disabled")
        return []

    try:
        from Bio import Entrez

        Entrez.email = settings.ncbi_email
        if settings.ncbi_api_key:
            Entrez.api_key = settings.ncbi_api_key

        # Search — run in thread since Entrez is blocking
        import asyncio
        loop = asyncio.get_event_loop()

        def _fetch():
            handle = Entrez.esearch(
                db="pubmed",
                term=query,
                retmax=max_results,
                sort="relevance",
            )
            search_results = Entrez.read(handle)
            handle.close()

            id_list = search_results.get("IdList", [])
            if not id_list:
                return [], []

            handle = Entrez.efetch(
                db="pubmed",
                id=",".join(id_list),
                rettype="xml",
                retmode="xml",
            )
            records = Entrez.read(handle)
            handle.close()
            return id_list, records

        id_list, records = await loop.run_in_executor(None, _fetch)
        if not id_list:
            return []

        results = []
        articles = records.get("PubmedArticle", [])
        for article in articles:
            try:
                medline = article.get("MedlineCitation", {})
                article_data = medline.get("Article", {})
                
                # Title
                title = str(article_data.get("ArticleTitle", ""))
                
                # Authors
                author_list = article_data.get("AuthorList", [])
                if author_list:
                    first = author_list[0]
                    last_name = first.get("LastName", "")
                    authors = f"{last_name} et al." if len(author_list) > 1 else last_name
                else:
                    authors = ""
                
                # Journal
                journal_info = article_data.get("Journal", {})
                journal = str(journal_info.get("Title", ""))
                
                # Year
                pub_date = journal_info.get("JournalIssue", {}).get("PubDate", {})
                year = str(pub_date.get("Year", ""))
                
                # PMID
                pmid = str(medline.get("PMID", ""))
                
                # Abstract
                abstract_parts = article_data.get("Abstract", {}).get("AbstractText", [])
                abstract = " ".join(str(p) for p in abstract_parts)[:500]
                
                results.append({
                    "title": title,
                    "authors": authors,
                    "journal": journal,
                    "year": year,
                    "pmid": pmid,
                    "abstract": abstract,
                })
            except Exception as e:
                logger.debug(f"Error parsing PubMed article: {e}")
                continue

        return results

    except ImportError:
        logger.warning("BioPython not installed — PubMed search disabled")
        return []
    except Exception as e:
        logger.error(f"PubMed search failed: {e}")
        return []
