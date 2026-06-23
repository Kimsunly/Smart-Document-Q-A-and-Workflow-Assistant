"""
FAISS vector index manager for multi-document retrieval.
"""
import faiss
import pickle
import numpy as np
from typing import List, Dict, Any, Tuple
from pathlib import Path


class FAISSIndexManager:
    """Manage FAISS index with metadata."""

    def __init__(self, dimension: int = 384):
        """
        Initialize index.

        Args:
            dimension: Embedding dimension (default: 384 for MiniLM)
        """
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)
        self.metadata = []

    def add_vectors(self, vectors: np.ndarray, metadata: List[Dict[str, Any]]):
        """
        Add vectors and metadata to index.

        Args:
            vectors: np.ndarray of shape (n, dimension)
            metadata: List of dicts with doc info
        """
        if len(vectors) != len(metadata):
            raise ValueError("vectors and metadata length mismatch")

        self.index.add(vectors.astype("float32"))
        self.metadata.extend(metadata)

    def search(self, query_vector: np.ndarray, k: int = 3) -> Tuple[List[float], List[Dict[str, Any]]]:
        """
        Search for similar chunks.

        Args:
            query_vector: Shape (dimension,) or (1, dimension)
            k: Number of results

        Returns:
            (distances, metadata_list)
        """
        if len(query_vector.shape) == 1:
            query_vector = query_vector.reshape(1, -1)

        distances, indices = self.index.search(
            query_vector.astype("float32"), k)

        results_metadata = [self.metadata[i]
                            for i in indices[0] if 0 <= i < len(self.metadata)]
        return distances[0].tolist(), results_metadata

    def save(self, path: str):
        """
        Save index and metadata to disk.

        Args:
            path: Path to save (without extension)
        """
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        faiss.write_index(self.index, f"{path}.faiss")

        # Save metadata
        with open(f"{path}.meta", "wb") as f:
            pickle.dump(self.metadata, f)

    @staticmethod
    def load(path: str) -> "FAISSIndexManager":
        """
        Load index from disk.

        Args:
            path: Path to load (without extension)

        Returns:
            FAISSIndexManager instance
        """
        manager = FAISSIndexManager()
        manager.index = faiss.read_index(f"{path}.faiss")

        with open(f"{path}.meta", "rb") as f:
            manager.metadata = pickle.load(f)

        return manager
