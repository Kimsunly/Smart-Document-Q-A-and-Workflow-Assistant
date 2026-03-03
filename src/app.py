from pdf2image import convert_from_bytes
from question_answering.tfidf_qa import get_best_answer
from text_processing.split_text import split_text_into_chunks
from text_processing.clean_text import clean_text
from document_processing.ocr.paddle_ocr import (
    extract_text_paddle,
    _paddle_available,
    set_paddle_ocr_instance
)
from document_processing.ocr.pytesseract_ocr import extract_text_from_image as tesseract_extract
from document_processing.extract_docx import extract_text_from_docx
from document_processing.extract_pdf import extract_text_from_pdf
import re
import io
import tempfile
import textwrap
import streamlit as st
import os
# 0=INFO, 1=WARNING, 2=ERROR, 3=FATAL
os.environ.setdefault("GLOG_minloglevel", "2")
# keep oneDNN CPU acceleration enabled
os.environ.setdefault("FLAGS_use_mkldnn", "1")


# Document processing (PDF/DOCX)

# OCR backends

# Text processing

# Question answering

# PDF to image conversion (requires Poppler installed & in PATH on Windows)


# -----------------------------
# Helpers
# -----------------------------
def looks_like_bad_ocr(text: str, min_len: int = 25) -> bool:
    """
    Heuristic to detect garbage/empty OCR outputs.
    """
    t = (text or "").strip()
    if len(t) < min_len:
        return True
    weird = len(re.findall(r"[^a-zA-Z0-9\s\.,;:\-\(\)\[\]']", t))
    return (weird / max(len(t), 1)) > 0.25


def run_ocr_on_image(path: str, mode: str, debug: bool = False):
    """
    Unified OCR runner for images.
    Returns: cleaned_text, preproc_preview_image, raw_text_output, confidence(0..100)
    NOTE: Each backend handles its own preprocessing internally.
    """
    if mode == "Tesseract (fast)":
        return tesseract_extract(path, debug=debug)

    if mode == "PaddleOCR (better handwriting)":
        if not _paddle_available:
            return "", None, "", 0.0
        return extract_text_paddle(path, debug=debug)

    # -------------------------
    # Auto mode: run both, choose best using heuristics
    # -------------------------
    t_clean, _, t_raw, t_conf = tesseract_extract(path, debug=False)

    if _paddle_available:
        p_clean, _, p_raw, p_conf = extract_text_paddle(path, debug=False)
    else:
        p_clean, p_raw, p_conf = "", "", 0.0

    t_bad = looks_like_bad_ocr(t_clean)
    p_bad = looks_like_bad_ocr(p_clean)

    # If one is clearly bad and the other isn't -> choose the good one
    if p_bad and not t_bad:
        return tesseract_extract(path, debug=debug)
    if t_bad and not p_bad and _paddle_available:
        return extract_text_paddle(path, debug=debug)

    # Both ok or both bad: choose by combined score (confidence + length)
    t_score = (t_conf * 1.0) + (min(len(t_clean), 500) * 0.03)
    p_score = (p_conf * 1.0) + (min(len(p_clean), 500) * 0.03)

    if _paddle_available and p_score > t_score:
        return extract_text_paddle(path, debug=debug)
    return tesseract_extract(path, debug=debug)


# -----------------------------
# Cache PaddleOCR instance (init once per Streamlit session)
# -----------------------------
@st.cache_resource(show_spinner=False)
def get_paddle_ocr():
    from paddleocr import PaddleOCR
    # Prefer new parameter; fall back for older PaddleOCR versions
    try:
        return PaddleOCR(lang="en", use_textline_orientation=True)
    except TypeError:
        return PaddleOCR(lang="en", use_angle_cls=True)


if _paddle_available:
    set_paddle_ocr_instance(get_paddle_ocr())


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Smart Document Q&A Assistant", page_icon="📄")
st.title("📄 Smart Document Q&A Assistant")
st.write("🚀 Upload PDF/DOCX or images. Choose OCR engine (Auto/Tesseract/Paddle).")

ocr_mode = st.radio(
    "🧠 OCR Engine",
    ("Auto", "Tesseract (fast)", "PaddleOCR (better handwriting)"),
    index=0,
    horizontal=True
)

if ocr_mode == "PaddleOCR (better handwriting)" and not _paddle_available:
    st.warning(
        "PaddleOCR not installed. Install `paddleocr` or choose Auto/Tesseract.")

uploaded_file = st.file_uploader(
    "📂 Upload a PDF or DOCX file", type=["pdf", "docx"])
uploaded_images = st.file_uploader(
    "📂 Upload one or more images (PNG/JPG/JPEG)",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True
)

text = ""


# -----------------------------
# PDF / DOCX handling
# -----------------------------
if uploaded_file is not None:
    name = uploaded_file.name.lower()

    # DOCX
    if name.endswith(".docx"):
        try:
            text = extract_text_from_docx(uploaded_file)
        except Exception as e:
            st.error(f"DOCX extraction error: {e}")

    # PDF
    elif name.endswith(".pdf"):
        file_bytes = uploaded_file.read()

        # 1) Try embedded text layer first (digital PDF)
        try:
            text = extract_text_from_pdf(io.BytesIO(file_bytes))
        except Exception:
            text = ""

        # 2) If no embedded text, do OCR on rendered pages
        if not text.strip():
            try:
                images = convert_from_bytes(file_bytes, dpi=300)

                for img in images:
                    tmp = tempfile.NamedTemporaryFile(
                        delete=False, suffix=".png")
                    tmp_path = tmp.name
                    tmp.close()
                    img.save(tmp_path)

                    cleaned, _, _, _ = run_ocr_on_image(
                        tmp_path, ocr_mode, debug=False)
                    text += cleaned + "\n"

                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

            except Exception as e:
                st.error(f"PDF OCR fallback error: {e}")


# -----------------------------
# Multiple images handling
# -----------------------------
all_preprocessed_images = []
all_raw_texts = []
all_cleaned_texts = []
all_confidences = []
uploaded_names = []

if uploaded_images:
    for uploaded_image in uploaded_images:
        uploaded_names.append(uploaded_image.name)
        st.success(f"✅ Uploaded: {uploaded_image.name}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
            tmp_file.write(uploaded_image.getvalue())
            tmp_file_path = tmp_file.name

        # IMPORTANT:
        # Do NOT preprocess globally here.
        # Each OCR backend handles preprocessing properly.
        try:
            cleaned, preproc_preview, raw, conf = run_ocr_on_image(
                tmp_file_path, ocr_mode, debug=True)
        except Exception as e:
            st.error(f"OCR error on {uploaded_image.name}: {e}")
            cleaned, preproc_preview, raw, conf = "", None, "", 0.0
            with st.expander("🔧 Paddle Debug (for troubleshooting)"):
                import paddle, paddleocr
                st.write("paddle:", paddle.__version__)
                st.write("paddleocr:", paddleocr.__version__)
                st.write("Paddle available:", _paddle_available)
        # Collect results
        all_preprocessed_images.append(preproc_preview)
        all_raw_texts.append(raw)
        all_cleaned_texts.append(cleaned)
        all_confidences.append(conf)
        text += cleaned + "\n"

        # Clean temp
        try:
            os.unlink(tmp_file_path)
        except Exception:
            pass

    # ---------- Display previews ----------
    for idx, name in enumerate(uploaded_names):
        st.markdown(f"### 📷 Image {idx+1}: {name}")

        # Original
        st.image(
            uploaded_images[idx], caption=f"Original — {name}", use_container_width=True)
        
        # Preprocessed preview if backend provides it
        if all_preprocessed_images[idx] is not None:
            st.image(
                all_preprocessed_images[idx], caption=f"Preprocessed (engine-specific) — {name}", use_container_width=True)

        # Raw OCR text
        st.subheader(f"Raw OCR Text — {name}")
        st.text_area(f"raw_{idx}", all_raw_texts[idx] or "", height=180)

        # Cleaned OCR text
        st.subheader(f"Cleaned OCR Text — {name}")
        st.text_area(f"cleaned_{idx}",
                    all_cleaned_texts[idx] or "", height=180)

        # Confidence
        st.metric("OCR Confidence", f"{all_confidences[idx]:.1f}%")

    # Overall average confidence
    if all_confidences:
        avg_conf = sum(all_confidences) / len(all_confidences)
        st.subheader(f"📊 Average OCR Confidence: {avg_conf:.1f}%")


# -----------------------------
# Downstream QA
# -----------------------------
if text.strip():
    st.subheader("📄 Document Text Preview (combined cleaned text)")
    st.text_area("combined_text", text[:4000], height=300)

    cleaned_for_qa = clean_text(text)
    st.subheader("🧹 Cleaned for QA (first 1000 chars)")
    st.text_area("cleaned_for_qa", cleaned_for_qa[:1000], height=200)

    chunks = split_text_into_chunks(cleaned_for_qa, chunk_size=200)
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
            f"**Question:** {user_question}  \n"
            f"**Answer:** {answer}  \n"
            f"**Similarity Score:** `{score:.2f}`"
        )
        with st.expander("Show raw answer details"):
            st.write({"question": user_question,
                     "answer": answer, "score": score})

elif (uploaded_file is not None) or (uploaded_images):
    st.warning("⚠️ No readable text found. Try uploading a clearer image or PDF.")
