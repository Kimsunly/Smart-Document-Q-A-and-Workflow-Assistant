import re

def split_text_into_chunks(
    text: str,
    doc_id: str,
    page: int,
    min_chars: int = 800,
    max_chars: int = 1200
):
    """
    Split text into character-based chunks with metadata.
    Robustly handles large paragraphs or text blocks by splitting on paragraphs,
    then sentences, then words/characters if necessary, keeping chunk sizes between
    min_chars and max_chars.

    Args:
        text: Text content to chunk
        doc_id: Document identifier
        page: Page number
        min_chars: Minimum chunk size in characters (default: 800)
        max_chars: Maximum chunk size in characters (default: 1200)

    Returns:
        List of dicts with keys: doc_id, page, chunk_id, text
    """
    if not text:
        return []

    # First, split by paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    
    # If there are no paragraphs, fallback to the text itself
    if not paragraphs:
        paragraphs = [text.strip()]

    # Helper function to split a single large paragraph into sentence-level blocks
    def split_large_paragraph(para_text: str) -> list:
        # Split by sentence boundaries, keeping punctuation
        sentences = re.split(r'(?<=[.!?])\s+', para_text)
        sub_chunks = []
        current_sub = ""
        
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            
            # If a single sentence is larger than max_chars, split it by words/chars
            if len(sent) > max_chars:
                if current_sub.strip():
                    sub_chunks.append(current_sub.strip())
                    current_sub = ""
                
                # Split by words
                words = sent.split(" ")
                word_buffer = ""
                for word in words:
                    if len(word_buffer) + len(word) + 1 <= max_chars:
                        word_buffer = f"{word_buffer} {word}".strip()
                    else:
                        if word_buffer:
                            sub_chunks.append(word_buffer)
                        # If a single word is larger than max_chars, split it hard by characters
                        if len(word) > max_chars:
                            for idx in range(0, len(word), max_chars):
                                sub_chunks.append(word[idx:idx+max_chars])
                            word_buffer = ""
                        else:
                            word_buffer = word
                if word_buffer:
                    sub_chunks.append(word_buffer)
            else:
                if len(current_sub) + (1 if current_sub else 0) + len(sent) <= max_chars:
                    if current_sub:
                        current_sub = f"{current_sub} {sent}"
                    else:
                        current_sub = sent
                else:
                    if current_sub:
                        sub_chunks.append(current_sub)
                    current_sub = sent
                    
        if current_sub.strip():
            sub_chunks.append(current_sub.strip())
            
        return sub_chunks

    # Now, process paragraphs and build chunks
    chunks = []
    buffer = ""
    chunk_id = 0

    # Expand any paragraphs that are too large into sentence-level blocks first
    expanded_paragraphs = []
    for para in paragraphs:
        if len(para) > max_chars:
            expanded_paragraphs.extend(split_large_paragraph(para))
        else:
            expanded_paragraphs.append(para)

    for para in expanded_paragraphs:
        # If adding the next paragraph fits within max_chars
        if len(buffer) + (2 if buffer else 0) + len(para) <= max_chars:
            if buffer:
                buffer += "\n\n" + para
            else:
                buffer = para
        else:
            # If the current buffer is large enough, save it
            if len(buffer) >= min_chars:
                chunks.append({
                    "doc_id": doc_id,
                    "page": page,
                    "chunk_id": f"{doc_id}_{page}_{chunk_id}",
                    "text": buffer.strip()
                })
                chunk_id += 1
                buffer = para
            else:
                # If current buffer is too small, but adding para makes it exceed max_chars,
                # we force-split or merge if it's the only option.
                if buffer.strip():
                    chunks.append({
                        "doc_id": doc_id,
                        "page": page,
                        "chunk_id": f"{doc_id}_{page}_{chunk_id}",
                        "text": buffer.strip()
                    })
                    chunk_id += 1
                buffer = para

    if buffer.strip():
        chunks.append({
            "doc_id": doc_id,
            "page": page,
            "chunk_id": f"{doc_id}_{page}_{chunk_id}",
            "text": buffer.strip()
        })

    return chunks
