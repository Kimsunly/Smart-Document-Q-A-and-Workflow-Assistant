import os
from document_processing.extract_pdf import extract_text_from_pdf
from document_processing.extract_docx import extract_text_from_docx
from text_processing.clean_text import clean_text
from text_processing.split_text import split_text_into_chunks
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ---------------- Utility Functions ----------------


def compute_f1(predicted, expected):
    """Compute token-level F1 score between predicted and expected answers."""
    pred_tokens = set(predicted.lower().split())
    exp_tokens = set(expected.lower().split())
    if not pred_tokens or not exp_tokens:
        return 0.0
    precision = len(pred_tokens & exp_tokens) / len(pred_tokens)
    recall = len(pred_tokens & exp_tokens) / len(exp_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * (precision * recall) / (precision + recall)


def load_document(file_path):
    """Load PDF or DOCX and return extracted text."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"{file_path} not found!")
    if file_path.lower().endswith(".pdf"):
        return extract_text_from_pdf(file_path)
    elif file_path.lower().endswith(".docx"):
        return extract_text_from_docx(file_path)
    else:
        raise ValueError("File must be PDF or DOCX")


def evaluate_questions(chunks, test_questions):
    """Evaluate multiple questions and print F1 + similarity scores."""
    for item in test_questions:
        question = item["question"]
        expected = item["expected_answer"]

        # Vectorize chunks + question
        vectorizer = TfidfVectorizer()
        X = vectorizer.fit_transform(chunks + [question])
        similarities = cosine_similarity(X[-1], X[:-1])
        best_idx = similarities.argmax()
        predicted_answer = chunks[best_idx]
        score = similarities[0][best_idx]

        # Compute F1
        f1 = compute_f1(predicted_answer, expected)

        # Print results
        print("Question:", question)
        print("Predicted Answer:", predicted_answer)
        print("Expected Answer:", expected)
        print(f"F1 Score: {f1:.2f}, Similarity Score: {score:.2f}")
        print("-" * 50)


# ---------------- Main Evaluation ----------------
if __name__ == "__main__":
    # 1️⃣ Provide your document path
    file_path = "your_doc.pdf"  # change to your file, e.g., "example.docx"

    # 2️⃣ Load & process document
    text = load_document(file_path)
    cleaned_text = clean_text(text)
    chunks = split_text_into_chunks(cleaned_text, chunk_size=100)

    # 3️⃣ Define test questions with expected answers
    test_questions = [
        {"question": "What is Machine Learning?",
            "expected_answer": "TF-IDF is a statistic for words"},
        {"question": "What is cosine similarity?",
            "expected_answer": "Cosine similarity measures vector similarity"},
        # Add more questions here
    ]

    # 4️⃣ Run evaluation
    evaluate_questions(chunks, test_questions)
