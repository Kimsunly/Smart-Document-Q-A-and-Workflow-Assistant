import tempfile
from pathlib import Path
from typing import List, Dict, Any
import json
from phase2.vector_db.faiss_index import FAISSIndexManager
from phase2.embeddings.embeddings import embed_chunks, embed_text
from text_processing.split_text import split_text_into_chunks
from document_processing.pdf_router import PDFRouter
from document_processing.extract_docx import extract_text_from_docx
from phase2.rag.rag_service import generate_rag_answer

from automation.config import (
    FAISS_INDEX_PATH,
    FAISS_INDEX_PATH_SHARED,
    FAISS_INDEX_PATH_TELEGRAM,
    FAISS_INDEX_PATH_SLACK,
    META_DIR
)


def get_index_path(source_name: str = None, channel: str = None) -> Path:
    """Determine the appropriate index path based on channel or source prefix."""
    if channel == "telegram" or (source_name and source_name.startswith("telegram:")):
        return FAISS_INDEX_PATH_TELEGRAM
    if channel == "slack" or (source_name and source_name.startswith("slack:")):
        return FAISS_INDEX_PATH_SLACK
    return FAISS_INDEX_PATH_SHARED


def _load_or_create_index(dimension: int = 384, path: Path = None):
    """Load FAISS index from a specific path or initialize a new one if missing."""
    if path is None:
        path = FAISS_INDEX_PATH_SHARED

    if path.with_suffix(".faiss").exists():
        mgr = FAISSIndexManager.load(str(path))
    else:
        mgr = FAISSIndexManager(dimension=dimension)
    return mgr


def process_and_index_bytes(file_bytes: bytes, filename: str, source_name: str, lang_mode: str = "eng"):
    """
    Write bytes to temp file -> route through PDFRouter (extract or OCR) -> chunk -> embed -> add to FAISS.
    Returns: {"meta": {...}, "indexed_chunks": n}
    """
    tmp = Path(tempfile.gettempdir()) / filename
    tmp.write_bytes(file_bytes)

    suffix = tmp.suffix.lower()
    router = PDFRouter()

    if suffix == ".docx":
        text = extract_text_from_docx(str(tmp))
        method = "docx_text_extraction"
        meta = {
            "file": str(tmp),
            "classification": "digital",
            "processing_method": method,
            "success": True,
        }
    elif suffix in {".txt", ".md", ".csv"}:
        text = tmp.read_text(encoding="utf-8", errors="ignore")
        method = "text_file_extraction"
        meta = {
            "file": str(tmp),
            "classification": "digital",
            "processing_method": method,
            "success": True,
        }
    else:
        text, method, meta = router.route_pdf(
            str(tmp), apply_ocr=True, lang_mode=lang_mode)
    tmp.unlink(missing_ok=True)

    doc_id = source_name or meta.get("file_id", filename)
    if source_name == "google_drive":
        doc_id = f"google_drive:{filename}"
    chunks = split_text_into_chunks(text, doc_id=doc_id, page=1)
    if not chunks:
        return {"meta": meta, "indexed_chunks": 0}

    for chunk in chunks:
        chunk["source_name"] = filename
        chunk["doc_id"] = doc_id

    target_path = get_index_path(source_name)
    vectors = embed_chunks(chunks)
    mgr = _load_or_create_index(dimension=vectors.shape[1], path=target_path)
    mgr.add_vectors(vectors, chunks)
    mgr.save(str(target_path))

    # Save simple metadata
    meta = dict(meta)
    meta["source_name"] = filename
    meta["channel"] = source_name or "streamlit"
    meta["doc_id"] = doc_id

    # Sanitize doc_id to replace invalid Windows filename characters (like :) with underscores
    safe_doc_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in doc_id)
    (META_DIR / f"{safe_doc_id}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"meta": meta, "indexed_chunks": len(chunks)}


def query_documents(question: str, top_k: int = 3, source_filter: str = None, channel: str = None) -> List[Dict[str, Any]]:
    """
    Query indexed documents using vector similarity.
    Supports filtering by specific document names/metadata.
    Returns list of dicts with: {text, source, score, chunk_id, ...}
    """
    try:
        target_path = get_index_path(source_filter, channel)
        mgr = _load_or_create_index(path=target_path)
        if mgr.index.ntotal == 0:
            return []

        query_vec = embed_text(question)
        search_k = min(50 if source_filter else top_k, mgr.index.ntotal)
        distances, results = mgr.search(query_vec, k=search_k)

        # Enrich results with scores and filter by source
        enriched = []
        for dist, item in zip(distances, results):
            row = dict(item)
            row["score"] = float(dist)
            row["source"] = row.get(
                "source_name", row.get("doc_id", "Unknown"))
            
            if source_filter:
                src_name = str(row.get("source_name", "")).lower()
                doc_id = str(row.get("doc_id", "")).lower()
                filt = source_filter.lower()
                if filt not in src_name and filt not in doc_id:
                    continue
                    
            enriched.append(row)
            if len(enriched) >= top_k:
                break

        return enriched
    except Exception as e:
        print(f"Error querying documents: {e}")
        return []


def answer_question(question: str, context: str = "", source_filter: str = None, channel: str = None) -> str:
    """
    Generate an answer to a question using RAG.
    If context not provided, retrieves from FAISS first.
    """
    try:
        retrieved = []
        if context:
            retrieved = [{"text": context, "score": 0.5}]
        else:
            # Retrieve from FAISS
            retrieved = query_documents(question, top_k=3, source_filter=source_filter, channel=channel)
            if retrieved:
                context = "\n\n".join([r.get("text", "") for r in retrieved])

        if not context:
            return "No relevant documents found to answer this question."

        # Generate answer using Ollama
        rag_result = generate_rag_answer(
            question=question,
            retrieved_chunks=retrieved,
            rag_mode="ollama",
            timeout_sec=30
        )

        return rag_result.get("answer", "Could not generate answer.")
    except Exception as e:
        print(f"Error generating answer: {e}")
        return f"Error generating answer: {str(e)[:100]}"
