from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def get_best_answer(question, chunks):
    if not chunks:
        return "No text available to answer.", 0.0

    # Extract text from chunk dicts
    chunk_texts = [c["text"] if isinstance(c, dict) else c for c in chunks]

    vectorizer = TfidfVectorizer()
    vectors = vectorizer.fit_transform([question] + chunk_texts)
    cosine_sim = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
    best_idx = cosine_sim.argmax()

    # Return the chunk dict if available, else just text
    best_chunk = chunks[best_idx]
    return best_chunk, cosine_sim[best_idx]
