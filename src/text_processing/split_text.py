
def split_text_into_chunks(
    text: str,
    doc_id: str,
    page: int,
    min_chars: int = 800,
    max_chars: int = 1200
):
    """
    Split text into character-based chunks with metadata.

    Args:
        text: Text content to chunk
        doc_id: Document identifier
        page: Page number
        min_chars: Minimum chunk size in characters (default: 800)
        max_chars: Maximum chunk size in characters (default: 1200)

    Returns:
        List of dicts with keys: doc_id, page, chunk_id, text
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    buffer = ""
    chunk_id = 0

    for para in paragraphs:
        if len(buffer) + len(para) <= max_chars:
            buffer += para + "\n\n"
        else:
            if len(buffer) >= min_chars:
                chunks.append({
                    "doc_id": doc_id,
                    "page": page,
                    "chunk_id": f"{doc_id}_{page}_{chunk_id}",
                    "text": buffer.strip()
                })
                chunk_id += 1
                buffer = para + "\n\n"
            else:
                buffer += para + "\n\n"

    if buffer.strip():
        chunks.append({
            "doc_id": doc_id,
            "page": page,
            "chunk_id": f"{doc_id}_{page}_{chunk_id}",
            "text": buffer.strip()
        })

    return chunks
