from phase2.embeddings.embeddings import embed_chunks, embed_text
from phase2.vector_db.faiss_index import FAISSIndexManager
from phase2.rag.rag_service import generate_rag_answer
from pathlib import Path
import sys

sys.path.insert(0, str(Path("src").resolve()))


chunks = [
    {
        "doc_id": "docA",
        "source_name": "docA.txt",
        "page": 1,
        "chunk_id": "docA_1_0",
        "text": "Employee benefits include health insurance and 15 days of annual leave.",
    },
    {
        "doc_id": "docB",
        "source_name": "docB.txt",
        "page": 2,
        "chunk_id": "docB_2_0",
        "text": "Training opportunities include leadership workshops, technical courses, and professional development modules.",
    },
    {
        "doc_id": "docC",
        "source_name": "docC.txt",
        "page": 1,
        "chunk_id": "docC_1_0",
        "text": "Office parking policy requires registration and monthly sticker renewal.",
    },
]

vectors = embed_chunks(chunks)
manager = FAISSIndexManager(dimension=vectors.shape[1])
manager.add_vectors(vectors, chunks)

question = "What training opportunities are available?"
query_vec = embed_text(question)
distances, retrieved = manager.search(query_vec, k=3)

print("Top-k retrieval:")
for i, item in enumerate(retrieved, 1):
    print(
        f"{i}. score={float(item.get('score', 0.0)):.4f} "
        f"chunk_id={item.get('chunk_id')} source={item.get('source_name')}"
    )

rag = generate_rag_answer(
    question=question,
    retrieved_chunks=retrieved,
    rag_mode="ollama",
    timeout_sec=60,
)

print("\nRAG output:")
print(f"provider={rag.get('provider')}")
print(f"answer={rag.get('answer')}")
print(f"context_chars={len(rag.get('context', ''))}")

unknown = generate_rag_answer(
    question="What is the CEO home address?",
    retrieved_chunks=[],
    rag_mode="local",
)

print("\nUnknown-question behavior:")
print(f"answer={unknown.get('answer')}")
