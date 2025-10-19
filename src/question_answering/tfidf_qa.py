from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def get_best_answer(question, chunks):
    if not chunks:
        return "No text available to answer.", 0.0
    vectorizer = TfidfVectorizer()
    vectors = vectorizer.fit_transform([question] + chunks)
    cosine_sim = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
    best_idx = cosine_sim.argmax()
    return chunks[best_idx], cosine_sim[best_idx]
