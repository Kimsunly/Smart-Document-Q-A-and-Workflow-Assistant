from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

texts = [
    "I love machine learning",
    "I love deep learning"
]

vectorizer = TfidfVectorizer().fit_transform(texts)
vectors = vectorizer.toarray()

similarity = cosine_similarity([vectors[0]], [vectors[1]])
print("Cosine similarity:", similarity[0][0])