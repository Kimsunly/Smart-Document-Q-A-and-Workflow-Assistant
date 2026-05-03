"""
Sentence embeddings generator using multilingual models.
"""
import io
from contextlib import redirect_stdout, redirect_stderr
import os
import numpy as np
from typing import List, Dict, Any

_EMBEDDINGS_MODEL = None


def get_embeddings_model():
    """Initialize and cache embeddings model."""
    global _EMBEDDINGS_MODEL

    if _EMBEDDINGS_MODEL is not None:
        return _EMBEDDINGS_MODEL

    # Reduce noisy transformer/hub logs in demo scripts.
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            ) from exc

    # Keep verification/demo output clean by silencing non-critical model load logs.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            _EMBEDDINGS_MODEL = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2",
                local_files_only=True,
            )
        except Exception:
            _EMBEDDINGS_MODEL = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )

    return _EMBEDDINGS_MODEL


def embed_chunks(chunks: List[Dict[str, Any]]) -> np.ndarray:
    """
    Generate embeddings for chunks.

    Args:
        chunks: List of chunk dicts with 'text' key

    Returns:
        np.ndarray of shape (len(chunks), 384) with float32 dtype
    """
    if not chunks:
        return np.array([], dtype="float32")

    model = get_embeddings_model()
    texts = [c["text"] for c in chunks]
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        vectors = model.encode(texts, normalize_embeddings=True)
    return vectors.astype("float32")


def embed_text(text: str) -> np.ndarray:
    """
    Embed a single text string.

    Args:
        text: Text to embed

    Returns:
        1D float32 array of shape (384,)
    """
    model = get_embeddings_model()
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        vector = model.encode(text, normalize_embeddings=True)
    return vector.astype("float32")
