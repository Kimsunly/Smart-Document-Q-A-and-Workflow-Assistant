import tempfile
from pathlib import Path
from phase2.vector_db.faiss_index import FAISSIndexManager
from phase2.embeddings.embeddings import embed_chunks
from text_processing.split_text import split_text_into_chunks
from document_processing.pdf_router import PDFRouter

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
    router = PDFRouter()
    text, method, meta = router.route_pdf(str(tmp), apply_ocr=True, lang_mode=lang_mode)
    tmp.unlink(missing_ok=True)

    doc_id = meta.get("file_id", filename)
    chunks = split_text_into_chunks(text, doc_id=doc_id, page=1)
    if not chunks:
        return {"meta": meta, "indexed_chunks": 0}

    vectors = embed_chunks(chunks)
    mgr = _load_or_create_index(dimension=vectors.shape[1])
    mgr.add_vectors(vectors, chunks)
    mgr.save(str(FAISS_INDEX_PATH))
    # Save simple metadata
    (META_DIR / f"{doc_id}.json").write_text(str(meta))
    return {"meta": meta, "indexed_chunks": len(chunks)}