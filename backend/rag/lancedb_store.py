"""
LanceDB Vector Store — serverless embedded vector DB for medical RAG.

Usage:
  python -m backend.rag.lancedb_store --init      # Initialize empty store
  python -m backend.rag.lancedb_store --ingest DIR # Ingest documents from DIR 
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from backend.config import get_settings

logger = logging.getLogger(__name__)

_db = None
_table = None
TABLE_NAME = "medical_knowledge"


def get_db():
    """Get or create LanceDB database."""
    global _db
    if _db is not None:
        return _db

    try:
        import lancedb

        settings = get_settings()
        db_path = settings.lancedb_abs_path
        db_path.mkdir(parents=True, exist_ok=True)

        _db = lancedb.connect(str(db_path))
        logger.info(f"Connected to LanceDB at {db_path}")
        return _db
    except ImportError:
        logger.warning("lancedb not installed. RAG disabled.")
        return None
    except Exception as e:
        logger.error(f"Failed to connect to LanceDB: {e}")
        return None


def get_table():
    """Get or create the medical knowledge table."""
    global _table
    if _table is not None:
        return _table

    db = get_db()
    if db is None:
        return None

    try:
        if TABLE_NAME in db.table_names():
            _table = db.open_table(TABLE_NAME)
        else:
            _table = _create_table(db)
        return _table
    except Exception as e:
        logger.error(f"Failed to get LanceDB table: {e}")
        return None


def _create_table(db):
    """Create the medical knowledge table with schema."""
    from backend.rag.embeddings import embed_single, get_embedding_dim

    dim = get_embedding_dim()

    # Create with a seed record
    seed = {
        "text": "ClinicalPilot medical knowledge base initialized.",
        "source": "system",
        "category": "system",
        "vector": embed_single("ClinicalPilot medical knowledge base initialized."),
    }

    table = db.create_table(TABLE_NAME, data=[seed])
    logger.info(f"Created LanceDB table '{TABLE_NAME}' with dim={dim}")
    return table


def add_documents(
    texts: list[str],
    sources: list[str] | None = None,
    categories: list[str] | None = None,
) -> int:
    """Add documents to the vector store. Returns count added."""
    table = get_table()
    if table is None:
        return 0

    from backend.rag.embeddings import embed_texts

    vectors = embed_texts(texts)

    if sources is None:
        sources = ["unknown"] * len(texts)
    if categories is None:
        categories = ["general"] * len(texts)

    data = [
        {"text": t, "source": s, "category": c, "vector": v}
        for t, s, c, v in zip(texts, sources, categories, vectors)
    ]

    table.add(data)
    logger.info(f"Added {len(data)} documents to LanceDB")
    return len(data)


def search(query: str, top_k: int = 5) -> list[dict]:
    """Search the vector store for relevant documents."""
    table = get_table()
    if table is None:
        return []

    from backend.rag.embeddings import embed_single

    query_vec = embed_single(query)

    try:
        results = (
            table.search(query_vec)
            .limit(top_k)
            .to_list()
        )
        return [
            {
                "text": r.get("text", ""),
                "source": r.get("source", ""),
                "category": r.get("category", ""),
                "score": r.get("_distance", 0),
            }
            for r in results
        ]
    except Exception as e:
        logger.error(f"LanceDB search failed: {e}")
        return []


def ingest_directory(dir_path: str) -> int:
    """Ingest all text/PDF files from a directory."""
    path = Path(dir_path)
    if not path.exists():
        logger.error(f"Directory not found: {dir_path}")
        return 0

    texts = []
    sources = []
    categories = []

    for file in path.rglob("*"):
        if file.suffix in (".txt", ".md"):
            content = file.read_text(encoding="utf-8", errors="replace")
            # Chunk into ~500 char segments
            chunks = _chunk_text(content, chunk_size=500, overlap=50)
            texts.extend(chunks)
            sources.extend([str(file.name)] * len(chunks))
            categories.extend(["document"] * len(chunks))

        elif file.suffix == ".pdf":
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(str(file))
                content = "\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
                chunks = _chunk_text(content, chunk_size=500, overlap=50)
                texts.extend(chunks)
                sources.extend([str(file.name)] * len(chunks))
                categories.extend(["document"] * len(chunks))
            except Exception as e:
                logger.warning(f"Failed to ingest {file}: {e}")

    if texts:
        return add_documents(texts, sources, categories)
    return 0


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


# ── CLI entrypoint ──────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if "--init" in sys.argv:
        print("Initializing LanceDB...")
        table = get_table()
        if table:
            print(f"✓ LanceDB initialized at {get_settings().lancedb_abs_path}")
        else:
            print("✗ Failed to initialize LanceDB")

    elif "--ingest" in sys.argv:
        idx = sys.argv.index("--ingest")
        if idx + 1 < len(sys.argv):
            dir_path = sys.argv[idx + 1]
            count = ingest_directory(dir_path)
            print(f"✓ Ingested {count} chunks from {dir_path}")
        else:
            print("Usage: python -m backend.rag.lancedb_store --ingest <directory>")
    else:
        print("Usage:")
        print("  python -m backend.rag.lancedb_store --init")
        print("  python -m backend.rag.lancedb_store --ingest <directory>")
