# src/app.py
import streamlit as st
import textwrap
import tempfile
import os

# Document processing (PDF/DOCX)
from document_processing.extract_pdf import extract_text_from_pdf
from document_processing.extract_docx import extract_text_from_docx

# OCR backends
from document_processing.ocr.pytesseract_ocr import extract_text_from_image as tesseract_extract
# may raise ImportError inside file
from document_processing.ocr.paddle_ocr import extract_text_paddle, _paddle_available

# Text processing
from text_processing.ocr_cleanup import clean_ocr_text
# your existing cleaning used for QA pipeline
from text_processing.clean_text import clean_text
from text_processing.split_text import split_text_into_chunks

# Question answering
from question_answering.tfidf_qa import get_best_answer

# PDF to image conversion
from pdf2image import convert_from_bytes

st.set_page_config(page_title="Smart Document Q&A Assistant", page_icon="📄")
st.title("📄 Smart Document Q&A Assistant")
st.write("🚀 Upload PDF/DOCX or images. Choose OCR engine (Auto/Tesseract/Paddle).")

# OCR engine selector
ocr_mode = st.radio(
    "🧠 OCR Engine",
    ("Auto", "Tesseract (fast)", "PaddleOCR (better handwriting)"),
    index=0,
    horizontal=True
)

if ocr_mode == "PaddleOCR (better handwriting)" and not _paddle_available:
    st.warning(
        "PaddleOCR not installed. Install `paddleocr` for handwriting mode or choose Auto/Tesseract.")

# Uploaders
uploaded_file = st.file_uploader(
    "📂 Upload a PDF or DOCX file", type=["pdf", "docx"])
uploaded_images = st.file_uploader("📂 Upload one or more images (PNG/JPG/JPEG)", type=[
                                   "png", "jpg", "jpeg"], accept_multiple_files=True)

text = ""

# PDF / DOCX handling
if uploaded_file is not None and uploaded_file.name.lower().endswith(".pdf"):
    try:
        images = convert_from_bytes(uploaded_file.read(), dpi=300)
        for img in images:
            # Step 1: create temp file
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp_file_path = tmp_file.name
            tmp_file.close()  # important! close it so OCR can access
            img.save(tmp_file_path)

            # Step 2: run OCR (Tesseract or Paddle)
            t_clean, _, _, _ = tesseract_extract(tmp_file_path, debug=False)
            text += t_clean + "\n"

            # Step 3: remove temp file
            os.unlink(tmp_file_path)

    except Exception as e:
        st.error(f"PDF conversion error: {e}")
        text = extract_text_from_pdf(uploaded_file)


# Multiple images handling
all_preprocessed_images = []
all_raw_texts = []
all_cleaned_texts = []
all_confidences = []
uploaded_names = []

if uploaded_images:
    # For Auto mode we will try both and pick best per image
    for uploaded_image in uploaded_images:
        uploaded_names.append(uploaded_image.name)
        st.success(f"✅ Uploaded: {uploaded_image.name}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
            tmp_file.write(uploaded_image.getvalue())
            tmp_file_path = tmp_file.name

        # Choose engine per ocr_mode
        try:
            if ocr_mode == "Tesseract (fast)":
                cleaned, preproc, raw, conf = tesseract_extract(
                    tmp_file_path, debug=True)
            elif ocr_mode == "PaddleOCR (better handwriting)":
                # paddle function may raise ImportError if not installed
                cleaned, preproc, raw, conf = extract_text_paddle(
                    tmp_file_path, debug=True)
            else:  # Auto - try both and pick higher avg confidence
                # Try Tesseract
                t_clean, t_preproc, t_raw, t_conf = tesseract_extract(
                    tmp_file_path, debug=False)
                # Try Paddle (if available)
                if _paddle_available:
                    p_clean, p_preproc, p_raw, p_conf = extract_text_paddle(
                        tmp_file_path, debug=False)
                else:
                    p_clean, p_preproc, p_raw, p_conf = "", None, "", 0.0

                # choose engine with higher confidence
                if p_conf > t_conf:
                    cleaned, preproc, raw, conf = p_clean, p_preproc, p_raw, p_conf
                    # for debug preview, re-run chosen with debug=True (to get preproc image)
                    if p_preproc is None:
                        cleaned, preproc, raw, conf = extract_text_paddle(
                            tmp_file_path, debug=True)
                else:
                    cleaned, preproc, raw, conf = t_clean, t_preproc, t_raw, t_conf
                    if t_preproc is None:
                        cleaned, preproc, raw, conf = tesseract_extract(
                            tmp_file_path, debug=True)
        except Exception as e:
            st.error(f"OCR error on {uploaded_image.name}: {e}")
            cleaned, preproc, raw, conf = "", None, "", 0.0

        # Append results
        all_preprocessed_images.append(preproc)
        all_raw_texts.append(raw)
        all_cleaned_texts.append(cleaned)
        all_confidences.append(conf)
        text += cleaned + "\n"

        # remove temp
        try:
            os.unlink(tmp_file_path)
        except Exception:
            pass

    # Display previews for all images
    for idx, name in enumerate(uploaded_names):
        st.markdown(f"### 📷 Image {idx+1}: {name}")
        # show original uploaded image
        st.image(
            uploaded_images[idx], caption=f"Original — {name}", use_container_width=True)

        # show preprocessed preview if available
        if all_preprocessed_images[idx] is not None:
            st.image(
                all_preprocessed_images[idx], caption=f"Preprocessed — {name}", use_container_width=True)

        # show raw OCR preview (exact words detected)
        st.subheader(f"Raw OCR Text — {name}")
        st.text_area(f"raw_{idx}", all_raw_texts[idx] or "", height=180)

        # show cleaned minimal text
        st.subheader(f"Cleaned OCR Text — {name}")
        st.text_area(f"cleaned_{idx}",
                     all_cleaned_texts[idx] or "", height=180)

        # confidence
        st.metric("OCR Confidence", f"{all_confidences[idx]:.1f}%")

    # overall avg confidence
    if all_confidences:
        avg_conf = sum(all_confidences) / len(all_confidences)
        st.subheader(f"📊 Average OCR Confidence: {avg_conf:.1f}%")

# Downstream processing (QA) using concatenated cleaned text
if text.strip():
    st.subheader("📄 Document Text Preview (combined cleaned text)")
    st.text_area("combined_text", text[:4000], height=300)

    # run your existing clean_text (if you use extra normalization before QA) and chunking
    cleaned_for_qa = clean_text(text)
    st.subheader("🧹 Cleaned for QA (first 1000 chars)")
    st.text_area("cleaned_for_qa", cleaned_for_qa[:1000], height=200)

    chunks = split_text_into_chunks(cleaned_for_qa, chunk_size=80)
    st.write(f"📑 Document split into {len(chunks)} chunks")

    st.subheader("Preview of first 5 chunks:")
    for i, chunk in enumerate(chunks[:5]):
        preview = textwrap.shorten(chunk, width=200, placeholder="...")
        st.write(f"Chunk {i+1}: {preview}")

    user_question = st.text_input("❓ Ask a question about this document:")
    if user_question:
        answer, score = get_best_answer(user_question, chunks)
        st.subheader("💡 Answer:")
        st.markdown(
            f"**Question:** {user_question}  \n**Answer:** {answer}  \n**Similarity Score:** `{score:.2f}`")
        with st.expander("Show raw answer details"):
            st.write({"question": user_question,
                     "answer": answer, "score": score})

# show warning only if user uploaded files/images but no text extracted
elif (uploaded_file is not None) or (uploaded_images):
    st.warning("⚠️ No readable text found. Try uploading a clearer image or PDF.")
