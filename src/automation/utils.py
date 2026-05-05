import tempfile
from pathlib import Path
from typing import List, Dict, Any
from phase2.vector_db.faiss_index import FAISSIndexManager
from phase2.embeddings.embeddings import embed_chunks, embed_text
from text_processing.split_text import split_text_into_chunks
from document_processing.pdf_router import PDFRouter
from document_processing.extract_docx import extract_text_from_docx
from phase2.rag.rag_service import generate_rag_answer

from automation.config import FAISS_INDEX_PATH, META_DIR


def _load_or_create_index(dimension: int = 384):
    if FAISS_INDEX_PATH.with_suffix(".faiss").exists():
        mgr = FAISSIndexManager.load(str(FAISS_INDEX_PATH))
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
    chunks = split_text_into_chunks(text, doc_id=doc_id, page=1)
    if not chunks:
        return {"meta": meta, "indexed_chunks": 0}

    for chunk in chunks:
        chunk["source_name"] = source_name or filename

    vectors = embed_chunks(chunks)
    mgr = _load_or_create_index(dimension=vectors.shape[1])
    mgr.add_vectors(vectors, chunks)
    mgr.save(str(FAISS_INDEX_PATH))
    # Save simple metadata
    meta = dict(meta)
    meta["source_name"] = source_name or filename
    meta["doc_id"] = doc_id
    (META_DIR / f"{doc_id}.json").write_text(str(meta))
    return {"meta": meta, "indexed_chunks": len(chunks)}


def query_documents(question: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Query indexed documents using vector similarity.
    Returns list of dicts with: {text, source, score, chunk_id, ...}
    """
    try:
        mgr = _load_or_create_index()
        if mgr.index.ntotal == 0:
            return []

        query_vec = embed_text(question)
        distances, results = mgr.search(
            query_vec, k=min(top_k, mgr.index.ntotal))

        # Enrich results with scores
        enriched = []
        for dist, item in zip(distances, results):
            row = dict(item)
            row["score"] = float(dist)
            row["source"] = row.get(
                "source_name", row.get("doc_id", "Unknown"))
            enriched.append(row)

        return enriched
    except Exception as e:
        print(f"Error querying documents: {e}")
        return []


def answer_question(question: str, context: str = "") -> str:
    """
    Generate an answer to a question using RAG.
    If context not provided, retrieves from FAISS first.
    """
    try:
        if not context:
            # Retrieve from FAISS
            results = query_documents(question, top_k=3)
            if results:
                context = "\n\n".join([r.get("text", "") for r in results])

        if not context:
            return "No relevant documents found to answer this question."

        # Generate answer using Ollama
        rag_result = generate_rag_answer(
            question=question,
            retrieved_chunks=[{"text": context, "score": 0.5}],
            rag_mode="ollama",
            timeout_sec=30
        )

        return rag_result.get("answer", "Could not generate answer.")
    except Exception as e:
        print(f"Error generating answer: {e}")
        return f"Error generating answer: {str(e)[:100]}"
