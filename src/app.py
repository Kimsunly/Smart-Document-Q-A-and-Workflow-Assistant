import streamlit as st
import textwrap

# Document processing
from document_processing.extract_pdf import extract_text_from_pdf
from document_processing.extract_docx import extract_text_from_docx

# Text processing
from text_processing.clean_text import clean_text
from text_processing.split_text import split_text_into_chunks

# Question answering
from question_answering.tfidf_qa import get_best_answer

# ---- Streamlit UI ----
st.set_page_config(page_title="Smart Document Q&A Assistant", page_icon="📄")
st.title("📄 Smart Document Q&A Assistant")
st.write("🚀 Upload a PDF or DOCX document to extract text and ask questions!")

# ---- File Upload ----
uploaded_file = st.file_uploader("📂 Upload a file", type=["pdf", "docx"])

if uploaded_file is not None:
    st.success(f"✅ Uploaded: {uploaded_file.name}")

    text = ""
    # Determine file type
    if uploaded_file.name.lower().endswith(".pdf"):
        text = extract_text_from_pdf(uploaded_file)
    elif uploaded_file.name.lower().endswith(".docx"):
        text = extract_text_from_docx(uploaded_file)

    if text.strip():
        # ---- Text Preview ----
        st.subheader("📄 Extracted Text Preview:")
        st.text_area("📝 Text Output", text, height=300)

        # ---- Text Cleaning ----
        cleaned_text = clean_text(text)
        st.subheader("🧹 Cleaned Text Preview (first 1000 chars):")
        st.text_area("Cleaned Text", cleaned_text[:1000], height=200)

        # ---- Split Text into Chunks ----
        chunks = split_text_into_chunks(cleaned_text, chunk_size=100)
        st.write(f"📑 Document split into {len(chunks)} chunks")

        st.subheader("Preview of first 5 chunks:")
        for i, chunk in enumerate(chunks[:5]):
            preview = textwrap.shorten(chunk, width=200, placeholder="...")
            st.write(f"Chunk {i+1}: {preview}")

        # ---- Question Input ----
        user_question = st.text_input("❓ Ask a question about this document:")

        if user_question:
            answer, score = get_best_answer(user_question, chunks)
            st.subheader("💡 Answer:")
            st.markdown(f"""
            **Question:** {user_question}  
            **Answer:** {answer}  
            **Similarity Score:** `{score:.2f}`
            """)
            # Optional: show raw details
            with st.expander("Show raw answer details"):
                st.write({
                    "question": user_question,
                    "answer": answer,
                    "score": score,
                })
    else:
        st.warning("⚠️ No readable text found in this document.")
