from pdf2image import convert_from_bytes
from question_answering.tfidf_qa import get_best_answer
from text_processing.split_text import split_text_into_chunks
from text_processing.clean_text import clean_text
from text_processing.document_format import format_document_text
from document_processing.ocr.paddle_ocr import (
    extract_text_paddle,
    _paddle_available,
    set_paddle_ocr_instance
)
from document_processing.ocr.pytesseract_ocr import extract_text_from_image as tesseract_extract
from document_processing.pdf_router import PDFRouter
from document_processing.extract_docx import extract_text_from_docx
from document_processing.extract_pdf import extract_text_from_pdf
import re
import io
import tempfile
import textwrap
import streamlit as st
import os
import pytesseract
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    from phase2.embeddings.embeddings import embed_chunks, embed_text
    from phase2.vector_db.faiss_index import FAISSIndexManager
    VECTOR_QA_AVAILABLE = True
except Exception:
    VECTOR_QA_AVAILABLE = False

from phase2.rag.rag_service import generate_rag_answer
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
    weird = len(re.findall(r"[^a-zA-Z0-9\s\.,;:\-\(\)\[\]'\"]", t))
    return (weird / max(len(t), 1)) > 0.25


def run_ocr_on_image(path: str, mode: str, lang_mode: str = "eng", debug: bool = False, ink_threshold: int = 18):
    """
    Unified OCR runner for images.
    Returns: cleaned_text, preproc_preview_image, raw_text_output, confidence(0..100)
    NOTE: Each backend handles its own preprocessing internally.
    """
    # Khmer/mixed route uses tuned Tesseract preprocessing in pytesseract_ocr.
    if "khm" in lang_mode:
        return tesseract_extract(path, lang_mode=lang_mode, debug=debug, ink_threshold=ink_threshold)

    if mode == "Tesseract (fast)":
        return tesseract_extract(path, lang_mode=lang_mode, debug=debug, ink_threshold=ink_threshold)

    if mode == "PaddleOCR (better handwriting)":
        if not _paddle_available:
            return "", None, "", 0.0
        # Paddle integration in this app currently supports English model.
        return extract_text_paddle(path, debug=debug, lang="en")

    # -------------------------
    # Auto mode: run both, choose best using heuristics
    # -------------------------
    t_clean, _, t_raw, t_conf = tesseract_extract(
        path, lang_mode=lang_mode, debug=False, ink_threshold=ink_threshold)

    if _paddle_available:
        p_clean, _, p_raw, p_conf = extract_text_paddle(
            path, debug=False, lang="en")
    else:
        p_clean, p_raw, p_conf = "", "", 0.0

    t_bad = looks_like_bad_ocr(t_clean)
    p_bad = looks_like_bad_ocr(p_clean)

    # If one is clearly bad and the other isn't -> choose the good one
    if p_bad and not t_bad:
        return tesseract_extract(path, lang_mode=lang_mode, debug=debug, ink_threshold=ink_threshold)
    if t_bad and not p_bad and _paddle_available:
        return extract_text_paddle(path, debug=debug, lang="en")

    # Both ok or both bad: choose by combined score (confidence + length)
    t_score = (t_conf * 1.0) + (min(len(t_clean), 500) * 0.03)
    p_score = (p_conf * 1.0) + (min(len(p_clean), 500) * 0.03)

    if _paddle_available and p_score > t_score:
        return extract_text_paddle(path, debug=debug, lang="en")
    return tesseract_extract(path, lang_mode=lang_mode, debug=debug, ink_threshold=ink_threshold)


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


def _init_state():
    st.session_state.setdefault("docs", [])
    st.session_state.setdefault("chunks", [])
    st.session_state.setdefault("vector_manager", None)
    st.session_state.setdefault("query_history", [])
    st.session_state.setdefault("ocr_pages", [])


def _build_index_from_docs(docs):
    all_chunks = []
    for doc in docs:
        cleaned = clean_text(doc.get("text", ""))
        doc_chunks = split_text_into_chunks(
            cleaned,
            doc_id=doc["doc_id"],
            page=1,
        )
        for c in doc_chunks:
            c["source_name"] = doc.get("source_name", doc["doc_id"])
        all_chunks.extend(doc_chunks)

    manager = None
    if VECTOR_QA_AVAILABLE and all_chunks:
        vectors = embed_chunks(all_chunks)
        manager = FAISSIndexManager(dimension=vectors.shape[1])
        manager.add_vectors(vectors, all_chunks)

    st.session_state["chunks"] = all_chunks
    st.session_state["vector_manager"] = manager


def _semantic_retrieve(query: str, top_k: int = 3):
    chunks = st.session_state.get("chunks", [])
    if not chunks:
        return []

    manager = st.session_state.get("vector_manager")
    if manager is not None and VECTOR_QA_AVAILABLE:
        q_vec = embed_text(query)
        distances, results = manager.search(q_vec, k=min(top_k, len(chunks)))
        enriched = []
        for dist, item in zip(distances, results):
            row = dict(item)
            row["score"] = float(dist)
            enriched.append(row)

        # If semantic similarity is too weak across all hits, use TF-IDF fallback.
        # This helps when embeddings are noisy for specific docs/languages.
        best = max((float(x.get("score", 0.0)) for x in enriched), default=0.0)
        if best >= 0.08:
            return enriched

    # TF-IDF fallback semantic retrieval
    texts = [c.get("text", "") for c in chunks]
    vect = TfidfVectorizer()
    mats = vect.fit_transform([query] + texts)
    sims = cosine_similarity(mats[0:1], mats[1:]).flatten()
    order = sims.argsort()[::-1][:min(top_k, len(chunks))]
    out = []
    for i in order:
        row = dict(chunks[i])
        row["score"] = float(sims[i])
        out.append(row)
    return out


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Smart Document Q&A Assistant", page_icon="📄")
st.title("📄 Smart Document Q&A Assistant")
st.write("🚀 Upload PDF/DOCX or images. Choose OCR engine (Auto/Tesseract/Paddle).")
_init_state()

ocr_mode = st.radio(
    "🧠 OCR Engine",
    (
        "Auto",
        "Tesseract (fast)",
        "PaddleOCR (better handwriting)",
    ),
    index=0,
    horizontal=True
)

ocr_language = st.radio(
    "🌐 OCR Language",
    ("English (eng)", "Khmer (khm)", "Mixed (eng+khm)"),
    index=0,
    horizontal=True
)

lang_mode = {
    "English (eng)": "eng",
    "Khmer (khm)": "khm",
    "Mixed (eng+khm)": "eng+khm",
}[ocr_language]

# Ink threshold tuning for Khmer blue-ink variants (used by Tesseract path)
ink_threshold = None
if "khm" in lang_mode:
    ink_threshold = st.slider(
        "🖋️ Ink detection threshold (blue ink tuning)",
        min_value=5,
        max_value=80,
        value=18,
        step=1,
        help="Lower=more sensitive to faint blue ink, Higher=ignore light noise"
    )

if "khm" in lang_mode and ocr_mode != "Tesseract (fast)":
    st.info("Khmer/Mixed mode selected: forcing Tesseract backend for better Khmer recognition.")
    ocr_mode = "Tesseract (fast)"

qa_mode = st.radio(
    "🔎 QA Retrieval",
    ("TF-IDF (baseline)", "Embeddings + FAISS"),
    index=1 if VECTOR_QA_AVAILABLE else 0,
    horizontal=True
)

rag_mode_ui = st.radio(
    "🧩 RAG Generation Mode",
    (
        "Local extractive (free)",
        "Ollama local LLM (free)",
    ),
    index=0,
    horizontal=True,
)

if rag_mode_ui == "Local extractive (free)":
    rag_mode = "local"
elif rag_mode_ui == "Ollama local LLM (free)":
    rag_mode = "ollama"
else:
    rag_mode = "local"

if qa_mode == "Embeddings + FAISS" and not VECTOR_QA_AVAILABLE:
    st.warning(
        "Embeddings/FAISS modules unavailable. Falling back to TF-IDF."
    )

if ocr_mode == "PaddleOCR (better handwriting)" and not _paddle_available:
    st.warning(
        "PaddleOCR not installed. Install `paddleocr` or choose Auto/Tesseract.")

if ocr_mode == "PaddleOCR (better handwriting)" and lang_mode != "eng":
    st.info(
        "PaddleOCR path in this app currently runs with English model. "
        "For Khmer/mixed tests, choose Tesseract (fast) or Auto."
    )

if "khm" in lang_mode:
    try:
        available_langs = set(pytesseract.get_languages(config=""))
    except Exception:
        available_langs = set()

    if "khm" not in available_langs:
        st.error(
            "Khmer OCR language pack is not installed in Tesseract. "
            "Please add khm.traineddata to your Tesseract tessdata folder: "
            "C:\\Program Files\\Tesseract-OCR\\tessdata"
        )

st.subheader("📄 Document Upload")
uploaded_files = st.file_uploader(
    "📂 Upload one or more PDF/DOCX files",
    type=["pdf", "docx"],
    accept_multiple_files=True,
    help="Use this for full document processing and QA."
)

st.subheader("🖼️ OCR Image Upload")
st.caption("Use this section to test OCR directly on image files.")
uploaded_images = st.file_uploader(
    "📂 Upload one or more images for OCR (PNG/JPG/JPEG)",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True,
    help="Each uploaded image will run through OCR and show raw/cleaned output plus confidence."
)

text = ""
pending_docs = []


# -----------------------------
# PDF / DOCX handling
# -----------------------------
if uploaded_files:
    router = PDFRouter(text_threshold=100)
    for uploaded_file in uploaded_files:
        name = uploaded_file.name.lower()

        # DOCX
        if name.endswith(".docx"):
            try:
                uploaded_file.seek(0)
                text = extract_text_from_docx(uploaded_file)
                if text.strip():
                    pending_docs.append(
                        {
                            "doc_id": "",
                            "source_name": uploaded_file.name,
                            "text": text,
                        }
                    )
                    st.success(f"✅ Processed DOCX: {uploaded_file.name}")
                else:
                    st.warning(
                        f"⚠️ No readable text in DOCX: {uploaded_file.name}")
            except Exception as e:
                st.error(f"DOCX extraction error ({uploaded_file.name}): {e}")

        # PDF
        elif name.endswith(".pdf"):
            uploaded_file.seek(0)
            file_bytes = uploaded_file.read()
            tmp_pdf_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                    tmp_pdf.write(file_bytes)
                    tmp_pdf_path = tmp_pdf.name

                text, processing_method, metadata = router.route_pdf(
                    tmp_pdf_path,
                    apply_ocr=True,
                    lang_mode=lang_mode
                )

                if text.strip():
                    pending_docs.append(
                        {
                            "doc_id": "",
                            "source_name": uploaded_file.name,
                            "text": text,
                        }
                    )
                    st.success(f"✅ Processed PDF: {uploaded_file.name}")
                else:
                    st.warning(
                        f"⚠️ No readable text in PDF: {uploaded_file.name}")

                st.caption(
                    f"{uploaded_file.name} -> "
                    f"classification: {metadata.get('classification', 'unknown')} | "
                    f"method: {processing_method} | chars: {metadata.get('char_count', 0)}"
                )

            except Exception as e:
                st.error(
                    f"PDF routing/processing error ({uploaded_file.name}): {e}")
            finally:
                if tmp_pdf_path:
                    try:
                        os.unlink(tmp_pdf_path)
                    except Exception:
                        pass


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
            uploaded_image.seek(0)
            tmp_file.write(uploaded_image.getvalue())
            tmp_file_path = tmp_file.name

        # IMPORTANT:
        # Do NOT preprocess globally here.
        # Each OCR backend handles preprocessing properly.
        try:
            cleaned, preproc_preview, raw, conf = run_ocr_on_image(
                tmp_file_path, ocr_mode, lang_mode=lang_mode, debug=True, ink_threshold=ink_threshold)
        except Exception as e:
            st.error(f"OCR error on {uploaded_image.name}: {e}")
            cleaned, preproc_preview, raw, conf = "", None, "", 0.0
            with st.expander("🔧 Paddle Debug (for troubleshooting)"):
                import paddle
                import paddleocr
                st.write("paddle:", paddle.__version__)
                st.write("paddleocr:", paddleocr.__version__)
                st.write("Paddle available:", _paddle_available)
        # Collect results
        all_preprocessed_images.append(preproc_preview)
        all_raw_texts.append(raw)
        all_cleaned_texts.append(cleaned)
        all_confidences.append(conf)
        text += cleaned + "\n"
        pending_docs.append(
            {
                "doc_id": "",
                "source_name": uploaded_image.name,
                "text": cleaned,
                "image_bytes": uploaded_image.getvalue(),
            }
        )
        st.session_state["ocr_pages"].append((uploaded_image.getvalue(), cleaned))

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
# Process & Index (Task 6)
# -----------------------------
if pending_docs:
    combined_text = "\n\n".join([d["text"]
                                for d in pending_docs if d["text"].strip()])
    st.subheader("📄 Document Text Preview (combined cleaned text)")
    preview_mode = st.selectbox(
        "Preview format",
        ("Formatted (conservative)", "Formatted (aggressive)", "Cleaned", "Raw"),
        index=0,
        help="Choose how to preview extracted text. Conservative keeps structure; aggressive merges more."
    )

    if preview_mode == "Raw":
        display_text = combined_text
    elif preview_mode == "Cleaned":
        # cleaned is what OCR returned (already cleaned)
        display_text = combined_text
    elif preview_mode == "Formatted (aggressive)":
        display_text = format_document_text(combined_text, mode="aggressive")
    else:
        display_text = format_document_text(combined_text, mode="conservative")

    st.text_area("combined_text", display_text[:4000], height=300)

col_a, col_b = st.columns(2)
with col_a:
    if st.button("⚙️ Process & Index Current Uploads", use_container_width=True):
        existing = st.session_state.get("docs", [])
        start_idx = len(existing) + 1
        for i, d in enumerate(pending_docs, start=start_idx):
            doc = dict(d)
            doc["doc_id"] = f"DOC_{i:03d}"
            existing.append(doc)
        st.session_state["docs"] = existing
        _build_index_from_docs(existing)
        st.success(
            f"Indexed {len(existing)} document(s), {len(st.session_state.get('chunks', []))} chunk(s)."
        )

with col_b:
    if st.button("🧹 Clear Index", use_container_width=True):
        st.session_state["docs"] = []
        st.session_state["chunks"] = []
        st.session_state["vector_manager"] = None
        st.session_state["query_history"] = []
        st.session_state["ocr_pages"] = []
        st.success("Index and history cleared.")

if st.session_state.get("docs"):
    st.caption(
        f"Indexed docs: {len(st.session_state['docs'])} | "
        f"Indexed chunks: {len(st.session_state.get('chunks', []))}"
    )

    with st.expander("Indexed Documents"):
        for d in st.session_state["docs"]:
            st.write({"doc_id": d.get("doc_id"),
                     "source_name": d.get("source_name")})

    with st.expander("Formatted Document Preview"):
        for d in st.session_state["docs"]:
            st.markdown(
                f"### {d.get('source_name', d.get('doc_id', 'Document'))}")
            if preview_mode == "Formatted (aggressive)":
                formatted_preview = format_document_text(
                    d.get("text", ""), mode="aggressive")
            elif preview_mode == "Raw":
                formatted_preview = d.get("text", "")
            else:
                formatted_preview = format_document_text(
                    d.get("text", ""), mode="conservative")

            st.text_area(
                f"formatted_{d.get('doc_id', d.get('source_name', 'doc'))}",
                formatted_preview[:4000],
                height=240,
            )


# -----------------------------
# Retrieval + RAG QA (Tasks 4 & 5)
# -----------------------------
if st.session_state.get("chunks"):
    top_k = st.slider("Top-k retrieval", min_value=1, max_value=8, value=3)

    st.caption("Suggested actions")
    quick_cols = st.columns(3)

    if quick_cols[0].button("Summarize the document", use_container_width=True):
        st.session_state["user_question"] = "What is this document about?"
        st.rerun()

    if quick_cols[1].button("Explain the assignment", use_container_width=True):
        st.session_state["user_question"] = "Explain this assignment and the requirements in simple steps."
        st.rerun()

    if quick_cols[2].button("Show next steps", use_container_width=True):
        st.session_state["user_question"] = "What steps should I follow to complete this document task?"
        st.rerun()

    with st.form("qa_form", clear_on_submit=False):
        st.caption(
            "Ask anything about the uploaded document. The assistant will answer using the document content.")
        user_question = st.text_input(
            "Ask about the document", key="user_question")
        ask_clicked = st.form_submit_button("Ask")

    if ask_clicked and user_question.strip():
        retrieved = _semantic_retrieve(user_question.strip(), top_k=top_k)

        if not retrieved:
            st.warning("No relevant chunks retrieved.")
        else:
            rag = generate_rag_answer(
                question=user_question.strip(),
                retrieved_chunks=retrieved,
                retries=2,
                # Increased for 3B model (needs ~30-60 sec for first response)
                timeout_sec=60,
                rag_mode=rag_mode,
            )

            best_chunk = retrieved[0]
            score = float(best_chunk.get("score", 0.0))

            st.subheader("Document Answer")
            st.markdown(rag["answer"])
            st.divider()
            st.caption(
                f"Best match: {score:.4f} | Reference chunk: {best_chunk.get('chunk_id', 'N/A')}"
                f" from {best_chunk.get('source_name', best_chunk.get('doc_id', 'N/A'))}"
            )

            with st.expander("Reference Context"):
                st.text_area("rag_context", rag["context"], height=240)

            with st.expander("Evidence Sources"):
                for i, item in enumerate(retrieved, start=1):
                    st.write(
                        {
                            "rank": i,
                            "score": round(float(item.get("score", 0.0)), 5),
                            "source": item.get("source_name", item.get("doc_id")),
                            "chunk_id": item.get("chunk_id"),
                            "page": item.get("page"),
                        }
                    )
                    st.caption(textwrap.shorten(
                        item.get("text", ""), width=260, placeholder="..."))

            st.caption(
                f"Provider: {rag['provider']} | attempts: {rag['attempts']} | "
                f"latency: {rag['elapsed_ms']} ms | est tokens: {rag['total_tokens_est']} | "
                f"est cost: ${rag['cost_usd_est']}"
            )

            if rag.get("provider") not in {"openai", "ollama"} and rag.get("last_error"):
                st.warning(
                    "RAG fallback reason: "
                    f"{rag['last_error']} | "
                    f"min_score={rag.get('fallback_min_score', 0.05):.2f}"
                )

            if rag_mode == "ollama" and rag.get("provider") != "ollama" and rag.get("last_error"):
                st.warning(
                    "Ollama not available, using extractive fallback. "
                    f"Reason: {rag['last_error']}"
                )

            st.session_state["query_history"].append(
                {
                    "question": user_question.strip(),
                    "answer": rag["answer"],
                    "top_score": round(score, 5),
                    "source": best_chunk.get("source_name", best_chunk.get("doc_id")),
                    "chunk_id": best_chunk.get("chunk_id"),
                }
            )

if st.session_state.get("query_history"):
    with st.expander("🕘 Query History"):
        for idx, h in enumerate(reversed(st.session_state["query_history"]), start=1):
            st.write(
                {
                    "#": idx,
                    "question": h["question"],
                    "answer": h["answer"],
                    "source": h["source"],
                    "chunk_id": h["chunk_id"],
                    "top_score": h["top_score"],
                }
            )

if (uploaded_files or uploaded_images) and not pending_docs:
    st.warning("⚠️ No readable text found. Try uploading a clearer image or PDF.")


# ═══════════════════════════════════════════════════════════════
# STRUCTURED DATA EXPORT (NEW FEATURE)
# ═══════════════════════════════════════════════════════════════

if st.session_state.get("docs"):
    st.divider()
    st.subheader("📊 Structured Data Export")
    st.caption(
        "Convert OCR-extracted content into canonical, machine-readable formats. "
        "Export files directly below."
    )
    
    try:
        from structured_data import DataExtractor, JSONExporter, CSVExporter, ExcelExporter
        
        # Get combined text from all docs
        combined_doc_text = "\n\n".join([d.get("text", "") for d in st.session_state.get("docs", [])])
        first_doc_name = st.session_state["docs"][0].get("source_name", "document") if st.session_state["docs"] else "document"
        
        # Initialize extractor
        extractor = DataExtractor(
            text=combined_doc_text,
            source_name=first_doc_name,
            doc_id="DOC_001"
        )
        
        # Extract all structures
        extracted_data = extractor.extract_all()
        
        # Premium Horizontal Grid with Direct Download Buttons
        export_cols = st.columns(3)
        
        # 1. JSON Card
        with export_cols[0]:
            st.markdown("""
            <div style="background-color:#1e293b; padding:15px; border-radius:10px; border-left:5px solid #6366f1; min-height:120px; margin-bottom:12px;">
                <h4 style="color:#ffffff; margin:0 0 5px 0; font-size:15px;">📋 JSON Output</h4>
                <p style="color:#94a3b8; font-size:11px; margin:0; line-height:1.4;">Standard internal schema containing fields, raw text, and metadata.</p>
            </div>
            """, unsafe_allow_html=True)
            json_str = JSONExporter.export(extracted_data, pretty=True)
            st.download_button(
                label="⬇️ Download JSON",
                data=json_str,
                file_name=f"{first_doc_name.replace('.pdf', '').replace('.docx', '').replace('.png', '').replace('.jpg', '').replace('.jpeg', '')}_export.json",
                mime="application/json",
                use_container_width=True,
                key="dl_json"
            )
        
        # 2. CSV Card
        with export_cols[1]:
            st.markdown("""
            <div style="background-color:#1e293b; padding:15px; border-radius:10px; border-left:5px solid #10b981; min-height:120px; margin-bottom:12px;">
                <h4 style="color:#ffffff; margin:0 0 5px 0; font-size:15px;">📝 CSV Format</h4>
                <p style="color:#94a3b8; font-size:11px; margin:0; line-height:1.4;">Flattened spreadsheet rows, optimal for fast database imports.</p>
            </div>
            """, unsafe_allow_html=True)
            records = extracted_data.get("records", [])
            if records:
                csv_str = CSVExporter.export_records(records)
                st.download_button(
                    label="⬇️ Download CSV",
                    data=csv_str,
                    file_name=f"{first_doc_name.replace('.pdf', '').replace('.docx', '').replace('.png', '').replace('.jpg', '').replace('.jpeg', '')}_records.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="dl_csv"
                )
            else:
                st.button("⬇️ CSV (Empty)", disabled=True, use_container_width=True, key="dl_csv_disabled")
        
        # 3. Excel Card
        with export_cols[2]:
            st.markdown("""
            <div style="background-color:#1e293b; padding:15px; border-radius:10px; border-left:5px solid #3b82f6; min-height:120px; margin-bottom:12px;">
                <h4 style="color:#ffffff; margin:0 0 5px 0; font-size:15px;">📊 Excel Sheets</h4>
                <p style="color:#94a3b8; font-size:11px; margin:0; line-height:1.4;">Professional workbook featuring frozen headers, auto-fit columns, and colored rows.</p>
            </div>
            """, unsafe_allow_html=True)
            try:
                excel_bytes = ExcelExporter.export(extracted_data)
                st.download_button(
                    label="⬇️ Download Excel",
                    data=excel_bytes,
                    file_name=f"{first_doc_name.replace('.pdf', '').replace('.docx', '').replace('.png', '').replace('.jpg', '').replace('.jpeg', '')}_export.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_excel"
                )
            except Exception as exc_err:
                st.error(f"Excel failed: {exc_err}")


        
        # Extraction Preview & Analytics
        st.write("")
        st.markdown("### 🔍 Extraction Preview & Analytics")
        
        with st.expander("📊 Detailed Extraction Metrics & Table Preview", expanded=True):
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Tables Found")
                tables = extracted_data.get("tables", [])
                if tables:
                    for idx, table in enumerate(tables, 1):
                        st.write(f"**Table {idx}**: {table.get('row_count', 0)} rows × {table.get('column_count', 0)} columns")
                        # Display small interactive table for preview!
                        if table.get("rows"):
                            import pandas as pd
                            df_preview = pd.DataFrame(table.get("rows"), columns=table.get("headers"))
                            st.dataframe(df_preview, use_container_width=True)
                else:
                    st.info("No tables detected")
            
            with col2:
                st.subheader("Records Detected")
                records = extracted_data.get("records", [])
                if records:
                    st.metric("Total Person/Student Records", len(records))
                    for record in records[:5]:  # Show first 5
                        st.markdown(f"- **{record.get('name', 'N/A')}** (ID: `{record.get('id', 'N/A')}`, Class: `{record.get('class', 'N/A')}`)")
                    if len(records) > 5:
                        st.caption(f"... and {len(records) - 5} more records")
                else:
                    st.info("No person records detected")
            
            st.write("")
            col3, col4 = st.columns(2)
            with col3:
                st.subheader("Key-Value Pairs (Forms)")
                kvp = extracted_data.get("key_value_pairs", {})
                if kvp:
                    st.json(kvp)
                else:
                    st.info("No form fields detected")
            with col4:
                st.subheader("Lists Detected")
                lists = extracted_data.get("lists", [])
                if lists:
                    for idx, lst in enumerate(lists, 1):
                        st.write(f"**List {idx}** ({lst.get('type', 'list')}): {lst.get('item_count', 0)} items")
                else:
                    st.info("No lists detected")
    
    except ImportError as e:
        st.warning(f"⚠️ Structured data module not available: {e}")
    except Exception as e:
        st.error(f"❌ Export error: {e}")

