"""
memory_indexer.py — HippoRAG wrapper для Case 10.

Препроцессор памяти: индексирует документы в граф знаний (триплеты),
позволяет делать multi-hop запросы через граф.

Использует HippoRAG 2 (https://github.com/osu-nlp-group/hipporag).
LLM для извлечения триплетов — через OpenRouter (API).
Embedding модель — CPU, int8.

Запуск: после pip install hipporag
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HippoRAG wrapper
# ---------------------------------------------------------------------------

_HIPPORAG_INSTANCE = None
_INDEXED_DOC_COUNT = 0


def _get_save_dir() -> Path:
    """Directory for HippoRAG persistent state (KG, indexes)."""
    base = os.environ.get("CASE10_HOME", str(Path.home() / ".case10"))
    save_dir = Path(base) / "hipporag"
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir


def _is_available() -> bool:
    """Check if hipporag package is installed and configured."""
    try:
        import hipporag  # noqa: F401
    except ImportError:
        return False
    # Need either OpenAI API key or local vLLM endpoint
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key and not os.environ.get("HIPPORAG_LLM_BASE_URL"):
        logger.warning(
            "HippoRAG: no LLM API key configured. "
            "Set OPENROUTER_API_KEY or HIPPORAG_LLM_BASE_URL"
        )
        return False
    return True


def _get_hipporag() -> Any:
    """Lazy-init HippoRAG singleton. Returns None if unavailable."""
    global _HIPPORAG_INSTANCE
    if _HIPPORAG_INSTANCE is not None:
        return _HIPPORAG_INSTANCE
    if not _is_available():
        return None

    try:
        from hipporag import HippoRAG
    except ImportError:
        return None

    llm_model = os.environ.get(
        "HIPPORAG_LLM_MODEL",
        "google/gemini-2.0-flash-001",
    )
    llm_base_url = os.environ.get("HIPPORAG_LLM_BASE_URL")
    embedding_model = os.environ.get(
        "HIPPORAG_EMBEDDING_MODEL",
        "nvidia/NV-Embed-v2",  # Can run on CPU
    )
    save_dir = str(_get_save_dir())

    try:
        kwargs = {
            "save_dir": save_dir,
            "llm_model_name": llm_model,
            "embedding_model_name": embedding_model,
        }
        # OpenRouter-compatible
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if api_key:
            kwargs["llm_base_url"] = llm_base_url or "https://openrouter.ai/api/v1"
            # Set key via env, HippoRAG reads OPENAI_API_KEY
            if not os.environ.get("OPENAI_API_KEY"):
                os.environ["OPENAI_API_KEY"] = api_key
        if llm_base_url:
            kwargs["llm_base_url"] = llm_base_url

        _HIPPORAG_INSTANCE = HippoRAG(**kwargs)
        logger.info(
            "HippoRAG initialized: model=%s embedding=%s",
            llm_model, embedding_model,
        )
        return _HIPPORAG_INSTANCE
    except Exception as exc:
        logger.error("HippoRAG init failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def index_document(text: str, doc_id: Optional[str] = None) -> dict:
    """Index a document into HippoRAG knowledge graph.

    Extracts triplets via LLM, builds/extends the KG.

    Args:
        text: Document text (meeting transcript, email, protocol, etc.)
        doc_id: Optional document identifier

    Returns:
        {"ok": True, "triplets": N, "doc_id": "..."} or {"ok": False, "error": "..."}
    """
    hr = _get_hipporag()
    if hr is None:
        return {"ok": False, "error": "HippoRAG not available"}

    global _INDEXED_DOC_COUNT
    doc_id = doc_id or f"doc-{int(time.time())}"

    try:
        hr.index(docs=[text])
        _INDEXED_DOC_COUNT += 1
        logger.info("Indexed doc %s (total: %d)", doc_id, _INDEXED_DOC_COUNT)
        return {
            "ok": True,
            "doc_id": doc_id,
            "total_indexed": _INDEXED_DOC_COUNT,
        }
    except Exception as exc:
        logger.error("HippoRAG index failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def query_memory(question: str, top_k: int = 5) -> dict:
    """Query the knowledge graph. Returns relevant passages + answer.

    Uses HippoRAG's PPR-based retrieval over the KG.

    Args:
        question: Natural language question
        top_k: Number of passages to retrieve

    Returns:
        {
            "ok": True,
            "question": "...",
            "answer": "...",       # LLM-generated answer from retrieved context
            "passages": [...],     # Retrieved relevant passages
            "triplets_hit": N,     # How many KG nodes were activated
        }
    """
    hr = _get_hipporag()
    if hr is None:
        return {"ok": False, "error": "HippoRAG not available"}

    try:
        # Retrieve relevant passages via PPR on KG
        retrieval = hr.retrieve(
            queries=[question],
            num_to_retrieve=top_k,
        )
        # Generate answer from retrieved context
        qa = hr.rag_qa(retrieval)

        # Parse results
        answer = ""
        retrieved_passages = []
        if qa and len(qa) > 0:
            qa_item = qa[0] if isinstance(qa, list) else qa
            answer = qa_item.get("answer", "") if isinstance(qa_item, dict) else str(qa_item)

        if retrieval and len(retrieval) > 0:
            r = retrieval[0] if isinstance(retrieval, list) else retrieval
            retrieved_passages = r if isinstance(r, list) else []

        return {
            "ok": True,
            "question": question,
            "answer": answer,
            "passages": retrieved_passages[:top_k],
            "total_indexed": _INDEXED_DOC_COUNT,
        }
    except Exception as exc:
        logger.error("HippoRAG query failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def memory_stats() -> dict:
    """Get memory index statistics."""
    hr = _get_hipporag()
    save_dir = _get_save_dir()

    stats = {
        "available": hr is not None,
        "total_indexed": _INDEXED_DOC_COUNT,
        "save_dir": str(save_dir),
        "kg_exists": (save_dir / "graph.json").exists() if hr else False,
    }

    if hr:
        try:
            # Try to get triplets count from graph
            graph_path = save_dir / "graph.json"
            if graph_path.exists():
                with open(graph_path) as f:
                    graph = json.load(f)
                stats["triplets"] = len(graph.get("triplets", []))
                stats["nodes"] = len(graph.get("nodes", []))
        except Exception:
            pass

    return stats


def reset_memory() -> dict:
    """Reset HippoRAG index. Clears the KG."""
    global _HIPPORAG_INSTANCE, _INDEXED_DOC_COUNT
    _HIPPORAG_INSTANCE = None
    _INDEXED_DOC_COUNT = 0

    save_dir = _get_save_dir()
    if save_dir.exists():
        import shutil
        shutil.rmtree(str(save_dir))
        save_dir.mkdir(parents=True)

    return {"ok": True, "message": "Memory reset"}
