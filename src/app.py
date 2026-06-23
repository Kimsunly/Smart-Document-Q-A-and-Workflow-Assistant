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
import time
import io
import tempfile
import textwrap
import streamlit as st
import os
from pathlib import Path
import pytesseract
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import json

try:
    from phase2.embeddings.embeddings import embed_chunks, embed_text
    from phase2.vector_db.faiss_index import FAISSIndexManager
    VECTOR_QA_AVAILABLE = True
except Exception:
    VECTOR_QA_AVAILABLE = False

from phase2.rag.rag_service import generate_rag_answer
from automation.config import FAISS_INDEX_PATH_SHARED, META_DIR
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
@st.cache_data(ttl=60)
def get_local_ollama_models():
    import urllib.request
    import json
    import os
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            if models:
                models.sort(key=lambda x: ("llama" not in x.lower(), x))
                return models
    except Exception:
        pass
    return ["llama3:latest", "llama3.2:3b", "qwen2.5-coder:14b", "deepseek-coder:6.7b", "tinyllama:latest"]

def parse_markdown_to_html(text: str) -> str:
    import re
    import html

    # 1. Escape HTML first to prevent injection/formatting breakages
    escaped = html.escape(text)

    # 2. Save code blocks first so we don't format contents
    code_blocks = []
    def save_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        code_blocks.append((lang, code))
        return f"<!--CODEBLOCK_{len(code_blocks)-1}-->"

    # Regex to match ```lang\ncode\n```
    pattern_code = re.compile(r"```([a-zA-Z0-9_\-+]*)\n(.*?)```", re.DOTALL)
    escaped = pattern_code.sub(save_code_block, escaped)

    # 3. Save inline code: `code`
    inline_codes = []
    def save_inline_code(match):
        code = match.group(1)
        inline_codes.append(code)
        return f"<!--INLINECODE_{len(inline_codes)-1}-->"

    pattern_inline = re.compile(r"`([^`\n]+)`")
    escaped = pattern_inline.sub(save_inline_code, escaped)

    # 4. Headings: ## Heading Name
    def format_heading(match):
        heading_text = match.group(1).strip()
        icon = "✨"
        if "answer" in heading_text.lower():
            icon = "💡"
        elif "evidence" in heading_text.lower():
            icon = "🔍"
        elif "next" in heading_text.lower():
            icon = "🎯"
        elif "summary" in heading_text.lower():
            icon = "📋"
        elif "key points" in heading_text.lower():
            icon = "🔑"
        elif "what the user" in heading_text.lower() or "do" in heading_text.lower():
            icon = "🚀"
        elif "notes" in heading_text.lower():
            icon = "📝"
            
        return f'<h4 class="chatgpt-section-header"><span class="chatgpt-header-icon">{icon}</span> {heading_text}</h4>'
        
    pattern_heading = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    escaped = pattern_heading.sub(format_heading, escaped)

    # 5. Bold: **text**
    escaped = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", escaped)

    # 6. Bullet lists: group consecutive list items
    lines = escaped.split("\n")
    in_list = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            item_content = stripped[2:]
            if not in_list:
                new_lines.append('<ul class="chatgpt-list">')
                in_list = True
            new_lines.append(f'<li>{item_content}</li>')
        else:
            if in_list:
                new_lines.append('</ul>')
                in_list = False
            new_lines.append(line)
    if in_list:
        new_lines.append('</ul>')
    escaped = "\n".join(new_lines)

    # 7. Restore inline code
    for idx, code in enumerate(inline_codes):
        escaped = escaped.replace(f"<!--INLINECODE_{idx}-->", f'<code class="chatgpt-inline-code">{code}</code>')

    # 8. Restore code blocks
    for idx, (lang, code) in enumerate(code_blocks):
        lang_label = lang if lang else "code"
        formatted_block = f"""
        <div class="chatgpt-code-block-container">
            <div class="chatgpt-code-block-header">
                <span>{lang_label}</span>
                <span class="chatgpt-copy-code-btn" onclick="const el = this; navigator.clipboard.writeText(el.parentElement.nextElementSibling.innerText.trim()); el.innerText = '✅ Copied!'; setTimeout(() => el.innerText = '📋 Copy code', 2000);">📋 Copy code</span>
            </div>
            <pre><code class="language-{lang}">{code}</code></pre>
        </div>
        """
        escaped = escaped.replace(f"<!--CODEBLOCK_{idx}-->", formatted_block)

    # 9. Format paragraphs
    paragraphs = escaped.split("\n\n")
    formatted_paragraphs = []
    for p in paragraphs:
        p_stripped = p.strip()
        if not p_stripped:
            continue
        # Skip wrapping tags that are block level
        if (p_stripped.startswith("<h4") or 
            p_stripped.startswith("<ul") or 
            p_stripped.startswith("<div class=\"chatgpt-code-block") or 
            p_stripped.startswith("<!--") or 
            p_stripped.startswith("</ul") or
            p_stripped.startswith("</div")):
            formatted_paragraphs.append(p_stripped)
        else:
            # Replace single newlines with <br/> for line breaks inside paragraphs
            p_formatted = p_stripped.replace("\n", "<br/>")
            formatted_paragraphs.append(f'<p class="chatgpt-p">{p_formatted}</p>')

    return "\n".join(formatted_paragraphs)


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
    st.session_state.setdefault("drive_files", [])
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("current_page", "Dashboard")
    st.session_state.setdefault("settings_ocr_mode", "Auto")
    st.session_state.setdefault("settings_ocr_lang", "English (eng)")
    st.session_state.setdefault("settings_ink_threshold", 18)
    st.session_state.setdefault("settings_qa_mode", "Embeddings + FAISS")
    st.session_state.setdefault("settings_rag_mode_ui", "Ollama local LLM (free)")
    st.session_state.setdefault("user_question", "")
    st.session_state.setdefault("trigger_query", False)
    st.session_state.setdefault("latest_rag_result", None)
    st.session_state.setdefault("latest_retrieved_chunks", [])
    st.session_state.setdefault("theme", "dark")
    
    # NEW state variables for premium 3-panel chat workspace
    st.session_state.setdefault("active_thread_id", "")
    st.session_state.setdefault("chat_threads", {
    })
    st.session_state.setdefault("chat_fullscreen", False)
    
    rag_mode_ui = st.session_state.get("settings_rag_mode_ui", "Ollama local LLM (free)")
    if rag_mode_ui == "Local extractive (free)":
        st.session_state.setdefault("hdr_model_select", "gpt-4o")
    else:
        local_models = get_local_ollama_models()
        default_local = local_models[0] if local_models else "llama3:latest"
        st.session_state.setdefault("hdr_model_select", default_local)

def sync_model_from_hdr():
    selected = st.session_state["hdr_model_select"]
    if selected == "gpt-4o":
        st.session_state["settings_rag_mode_ui"] = "Local extractive (free)"
    else:
        st.session_state["settings_rag_mode_ui"] = "Ollama local LLM (free)"
        
    active_id = st.session_state.get("active_thread_id")
    if active_id and active_id in st.session_state.get("chat_threads", {}):
        st.session_state["chat_threads"][active_id]["model"] = selected


def sync_model_from_sidebar():
    selected = st.session_state["settings_rag_mode_ui"]
    if selected == "Local extractive (free)":
        st.session_state["hdr_model_select"] = "gpt-4o"
    else:
        local_models = get_local_ollama_models()
        default_local = local_models[0] if local_models else "llama3:latest"
        st.session_state["hdr_model_select"] = default_local
        
    active_id = st.session_state.get("active_thread_id")
    if active_id and active_id in st.session_state.get("chat_threads", {}):
        st.session_state["chat_threads"][active_id]["model"] = st.session_state["hdr_model_select"]


def _build_index_from_docs(docs):
    with st.spinner("Processing documents and rebuilding vector index..."):
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


def _semantic_retrieve(query: str, top_k: int = 3, filter_docs: list = None):
    chunks = st.session_state.get("chunks", [])
    if not chunks:
        return []

    # Filter chunks list if filter_docs is provided
    if filter_docs:
        filter_docs_lower = [d.lower() for d in filter_docs]
        chunks = [c for c in chunks if str(c.get("source_name", "")).lower() in filter_docs_lower]
        if not chunks:
            return []

    manager = st.session_state.get("vector_manager")
    if manager is not None and VECTOR_QA_AVAILABLE:
        q_vec = embed_text(query)
        # Search a larger pool (k) to allow for post-filtering if filters are active
        search_k = min(50 if filter_docs else top_k, len(chunks))
        distances, results = manager.search(q_vec, k=search_k)
        
        enriched = []
        for dist, item in zip(distances, results):
            row = dict(item)
            row["score"] = float(dist)
            
            # Apply filter to vector search results
            if filter_docs:
                src = str(row.get("source_name", "")).lower()
                if src not in [d.lower() for d in filter_docs]:
                    continue
            
            enriched.append(row)
            if len(enriched) >= top_k:
                break

        if enriched:
            best = max((float(x.get("score", 0.0)) for x in enriched), default=0.0)
            if best >= 0.08:
                return enriched

    # TF-IDF fallback semantic retrieval on filtered chunks
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
# Active Pipeline Health Checks
# -----------------------------
def load_meta_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        try:
            return json.loads(content)
        except Exception:
            try:
                import ast
                return ast.literal_eval(content)
            except Exception:
                fixed = content.replace("True", "true").replace("False", "false").replace("None", "null")
                fixed = fixed.replace("'", "\"")
                return json.loads(fixed)
    except Exception:
        return {}


def check_redis_health() -> tuple[str, str]:
    start = time.time()
    try:
        import redis
        from automation.config import REDIS_URL
        r = redis.from_url(REDIS_URL, socket_timeout=1.0)
        r.ping()
        latency = f"{int((time.time() - start) * 1000)}ms"
        return "Healthy", latency
    except Exception:
        return "Offline", "—"


def check_ollama_health() -> tuple[str, str]:
    start = time.time()
    try:
        import urllib.request
        url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as response:
            if response.status == 200:
                latency = f"{int((time.time() - start) * 1000)}ms"
                return "Healthy", latency
    except Exception:
        pass
    return "Offline", "—"


def check_gdrive_health() -> tuple[str, str]:
    start = time.time()
    from automation.config import GOOGLE_CREDENTIALS_JSON
    drive_folder_id = os.getenv("DRIVE_FOLDER_ID", "")
    if not drive_folder_id:
        return "Warning", "—"
    cred_file = Path("credentials/google_drive_service_account.json")
    if cred_file.exists() or GOOGLE_CREDENTIALS_JSON:
        latency = f"{int((time.time() - start) * 1000)}ms"
        return "Healthy", latency
    return "Offline", "—"


def check_telegram_health() -> tuple[str, str]:
    start = time.time()
    from automation.config import TELEGRAM_BOT_TOKEN
    if TELEGRAM_BOT_TOKEN:
        latency = f"{int((time.time() - start) * 1000)}ms"
        return "Healthy", latency
    return "Offline", "—"


def check_slack_health() -> tuple[str, str]:
    start = time.time()
    from automation.config import SLACK_BOT_TOKEN
    if SLACK_BOT_TOKEN:
        latency = f"{int((time.time() - start) * 1000)}ms"
        return "Healthy", latency
    return "Offline", "—"


def check_faiss_health() -> tuple[str, str]:
    start = time.time()
    from automation.config import FAISS_INDEX_PATH_SHARED
    if FAISS_INDEX_PATH_SHARED.with_suffix(".faiss").exists():
        latency = f"{int((time.time() - start) * 1000)}ms"
        return "Healthy", latency
    return "Offline", "—"


def get_dashboard_metrics():
    import glob
    import os
    import time
    from automation.config import META_DIR
    
    meta_files = glob.glob(str(META_DIR / "*.json"))
    doc_meta_files = [f for f in meta_files if not os.path.basename(f).startswith("drive_poller_state")]
    
    now = time.time()
    cutoff_24h = now - 24 * 3600
    
    docs_count = 0
    docs_past_count = 0
    
    ocr_count = 0
    ocr_past_count = 0
    
    chunks_count = 0
    chunks_past_count = 0
    
    activities = []
    gdrive_latest_mtime = 0
    slack_channels = set()
    telegram_active = False
    
    for path in doc_meta_files:
        try:
            m = load_meta_file(path)
            if not m:
                continue
                
            src = m.get("source_name", "Unknown File")
            channel = m.get("channel", "streamlit")
            method = m.get("processing_method", "")
            classification = m.get("classification", "")
            
            mtime = os.path.getmtime(path)
            is_recent = mtime >= cutoff_24h
            
            docs_count += 1
            if not is_recent:
                docs_past_count += 1
                
            is_ocr = (classification == "scanned" or method == "ocr_pdf")
            if is_ocr:
                ocr_count += 1
                if not is_recent:
                    ocr_past_count += 1
                    
            doc_chunks_count = m.get("chunk_count")
            if doc_chunks_count is None:
                char_count = m.get("char_count", 0)
                doc_chunks_count = max(1, char_count // 500)
            
            chunks_count += doc_chunks_count
            if not is_recent:
                chunks_past_count += doc_chunks_count
            
            if channel == "google_drive":
                chan_label = "Google Drive"
                if mtime > gdrive_latest_mtime:
                    gdrive_latest_mtime = mtime
            elif channel.startswith("telegram:"):
                chan_label = "Telegram"
                telegram_active = True
            elif channel.startswith("slack:"):
                chan_label = "Slack"
                chan_id = channel.split(":", 1)[1] if ":" in channel else "unknown"
                slack_channels.add(chan_id)
            else:
                chan_label = "Web UI"
                
            activities.append({
                "time": mtime,
                "text": f"Successfully indexed <b>{src}</b> via <i>{chan_label}</i> (Method: {method or 'unknown'})"
            })
        except Exception:
            continue
            
    mgr = st.session_state.get("vector_manager")
    if mgr:
        chunks_count = mgr.index.ntotal
    else:
        from automation.config import FAISS_INDEX_PATH_SHARED
        if FAISS_INDEX_PATH_SHARED.with_suffix(".faiss").exists():
            try:
                shared_mgr = FAISSIndexManager.load(str(FAISS_INDEX_PATH_SHARED))
                chunks_count = shared_mgr.index.ntotal
            except Exception:
                pass
                
    def format_delta(current, past):
        if past == 0:
            return f"+{current * 100:.1f}%" if current > 0 else "+0.0%"
        growth = current - past
        percentage = (growth / past) * 100
        return f"+{percentage:.1f}%" if percentage >= 0 else f"{percentage:.1f}%"
        
    docs_delta = format_delta(docs_count, docs_past_count)
    ocr_delta = format_delta(ocr_count, ocr_past_count)
    chunks_delta = format_delta(chunks_count, chunks_past_count)
    
    vector_gb = round(chunks_count * 0.000366, 1)
    vector_gb_past = round(chunks_past_count * 0.000366, 1)
    vector_delta = format_delta(vector_gb, vector_gb_past)
    
    if gdrive_latest_mtime > 0:
        elapsed = time.time() - gdrive_latest_mtime
        if elapsed < 60:
            gdrive_meta = "Synced just now"
        elif elapsed < 3600:
            gdrive_meta = f"Synced {int(elapsed // 60)}m ago"
        elif elapsed < 86400:
            gdrive_meta = f"Synced {int(elapsed // 3600)}h ago"
        else:
            gdrive_meta = f"Synced {int(elapsed // 86400)}d ago"
    else:
        gdrive_meta = "No synced files"
        
    slack_channel_count = len(slack_channels)
    slack_meta = f"{slack_channel_count} channels active" if slack_channel_count > 0 else "No active channels"
    
    telegram_meta = "Active polling" if telegram_active else "Idle"
    
    activities.sort(key=lambda x: x["time"], reverse=True)
    
    return {
        "docs_count": docs_count,
        "docs_delta": docs_delta,
        "ocr_count": ocr_count,
        "ocr_delta": ocr_delta,
        "total_chunks": chunks_count,
        "chunks_delta": chunks_delta,
        "vector_gb": vector_gb,
        "vector_delta": vector_delta,
        "activities": activities[:8],
        "gdrive_meta": gdrive_meta,
        "slack_meta": slack_meta,
        "telegram_meta": telegram_meta
    }


def trigger_sync_workspace():
    try:
        from automation.config import FAISS_INDEX_PATH_SHARED
        if FAISS_INDEX_PATH_SHARED.with_suffix(".faiss").exists():
            shared_mgr = FAISSIndexManager.load(str(FAISS_INDEX_PATH_SHARED))
            docs_by_id = {}
            for chunk in shared_mgr.metadata:
                d_id = chunk.get("doc_id", "Unknown")
                src = chunk.get("source_name", d_id)
                if d_id not in docs_by_id:
                    docs_by_id[d_id] = {
                        "doc_id": d_id,
                        "source_name": src,
                        "text": ""
                    }
                docs_by_id[d_id]["text"] += chunk.get("text", "") + "\n\n"
            st.session_state["docs"] = list(docs_by_id.values())
            st.session_state["chunks"] = shared_mgr.metadata
            st.session_state["vector_manager"] = shared_mgr
    except Exception:
        pass


# -----------------------------
# Redesigned Page Renderers
# -----------------------------
def render_hero_section(metrics):
    docs_count = metrics["docs_count"]
    docs_delta = metrics["docs_delta"]
    total_chunks = metrics["total_chunks"]
    chunks_delta = metrics["chunks_delta"]
    vector_gb = metrics["vector_gb"]
    vector_delta = metrics["vector_delta"]
    ocr_count = metrics["ocr_count"]
    ocr_delta = metrics["ocr_delta"]

    st.markdown(f"""
    <div class="page-header">
        <div class="page-header-left">
            <div class="page-eyebrow">SmartDoc AI · Document Intelligence</div>
            <h1 class="page-title">Overview</h1>
            <p class="page-subtitle">Activity across your document intelligence workspace.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Documents indexed</div>
            <div class="metric-value">{docs_count:,}</div>
            <div class="metric-delta">{docs_delta}</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Total chunks</div>
            <div class="metric-value">{total_chunks:,}</div>
            <div class="metric-delta">{chunks_delta}</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Vector DB size</div>
            <div class="metric-value">{vector_gb} GB</div>
            <div class="metric-delta">{vector_delta}</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">OCR processed</div>
            <div class="metric-value">{ocr_count:,}</div>
            <div class="metric-delta">{ocr_delta}</div>
        </div>""", unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:32px'></div>", unsafe_allow_html=True)



def render_document_management():
    st.markdown("""
    <div style="padding-bottom:18px;border-bottom:1px solid var(--border-soft);margin-bottom:24px;">
        <div class="page-eyebrow">Ingestion</div>
        <h2 style="font-family:Outfit;font-size:20px;font-weight:700;color:var(--text-bright);margin:2px 0 4px 0;letter-spacing:-0.025em;">Document Hub</h2>
        <p style="font-size:13px;color:var(--text-muted);margin:0;">Ingest files locally or fetch from Google Drive, then build and sync the vector index.</p>
    </div>
    """, unsafe_allow_html=True)
    
    doc_cols = st.columns([1, 1])
    
    with doc_cols[0]:
        st.markdown("<p class='section-heading'>Local file upload</p>", unsafe_allow_html=True)
        uploaded_files = st.file_uploader(
            "Upload PDF or DOCX files:",
            type=["pdf", "docx"],
            accept_multiple_files=True,
            key="local_file_uploader",
            help="Direct text extraction for digital files, OCR auto-routing for scanned files."
        )
        
        uploaded_images = st.file_uploader(
            "Upload image files for testing OCR (PNG/JPG/JPEG):",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="local_image_uploader",
            help="Images are preprocessed and run through the selected OCR engine."
        )
        
    with doc_cols[1]:
        st.markdown("<p class='section-heading'>Google Drive hub</p>", unsafe_allow_html=True)
        drive_folder_id = os.getenv("DRIVE_FOLDER_ID", "")
        if drive_folder_id:
            if st.session_state.get("drive_files"):
                file_options = {f["name"]: f["id"] for f in st.session_state["drive_files"]}
                selected_file_name = st.selectbox(
                    "Select Google Drive file to index:",
                    options=list(file_options.keys())
                )
                selected_file_id = file_options[selected_file_name]
                
                if st.button("📥 Index Selected Google Drive File", use_container_width=True):
                    try:
                        from automation.drive_poller import _build_service, download_file
                        from automation.utils import process_and_index_bytes
                        with st.spinner(f"Downloading {selected_file_name}..."):
                            service = _build_service()
                            file_bytes = download_file(service, selected_file_id)
                        with st.spinner("Indexing vector database..."):
                            process_and_index_bytes(file_bytes, selected_file_name, "google_drive", lang_mode=lang_mode)
                        st.success(f"Successfully indexed {selected_file_name}!")
                        trigger_sync_workspace()
                    except Exception as e:
                        st.error(f"Download failed: {e}")
            else:
                st.caption("No files found or service account unconfigured.")
                
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                if st.button("🔄 Refresh GDrive List", use_container_width=True):
                    try:
                        from automation.drive_poller import _build_service, list_files_in_folder
                        service = _build_service()
                        st.session_state["drive_files"] = list_files_in_folder(service, drive_folder_id)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to refresh list: {e}")
            with col_d2:
                if st.button("📡 Background Poll Folder", use_container_width=True):
                    try:
                        from automation.drive_poller import poll_drive_folder
                        with st.spinner("Triggering polling check..."):
                            poll_drive_folder(drive_folder_id, lang_mode=lang_mode)
                        st.success("Polled folder. Background Celery tasks queued!")
                    except Exception as e:
                        st.error(f"Polling failed: {e}")
        else:
            st.info("Set DRIVE_FOLDER_ID in your .env file to enable Google Drive explorer.")
            
    # Process uploads
    process_uploads_pipeline(uploaded_files, uploaded_images)
    
    st.markdown("<div style='margin-top:32px'></div>", unsafe_allow_html=True)
    st.markdown("<p class='section-heading'>Indexed documents</p>", unsafe_allow_html=True)
    
    col_repo1, col_repo2 = st.columns([3, 1])
    with col_repo1:
        st.markdown("<p style='color:#94A3B8; font-size:13px; margin:0;'>View all files currently active in your local workspace or sync the shared database.</p>", unsafe_allow_html=True)
    with col_repo2:
        if st.button("🔄 Sync Workspace Index", use_container_width=True, key="doc_sync_index_btn"):
            trigger_sync_workspace()
            st.success("Synchronized!")
            st.rerun()
            
    # List documents
    docs = st.session_state.get("docs", [])
    if not docs:
        st.markdown("""
        <div class="empty-state-card">
            No documents currently indexed. Drag-and-drop files above, or click "Sync Workspace Index" to fetch previously saved indices.
        </div>
        """, unsafe_allow_html=True)
    else:
        for idx, doc in enumerate(docs):
            d_id = doc.get("doc_id", "Unknown")
            name = doc.get("source_name", "document")
            text_preview = doc.get("text", "")[:250] + "..."
            
            icon = "📄"
            if d_id.startswith("google_drive:"):
                badge = "Google Drive"
                badge_bg = "rgba(59, 130, 246, 0.1)"
                badge_color = "#3B82F6"
            elif d_id.startswith("DOC_"):
                badge = "Local Ingestion"
                badge_bg = "rgba(139, 92, 246, 0.1)"
                badge_color = "#8B5CF6"
            else:
                badge = "System Sync"
                badge_bg = "rgba(16, 185, 129, 0.1)"
                badge_color = "#10B981"
                
            col_card_a, col_card_b = st.columns([5, 1])
            with col_card_a:
                st.markdown(f"""
                <div class="doc-list-card">
                    <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 6px;">
                        <span style="font-size: 16px;">{icon}</span>
                        <span style="color: var(--text-bright); font-weight: 600; font-family: Inter; font-size: 14px;">{name}</span>
                        <span style="background-color: {badge_bg}; color: {badge_color}; padding: 1px 8px; border-radius: 12px; font-size: 10px; font-weight: 600;">{badge}</span>
                        <span style="color: var(--text-muted); font-size: 11px;">ID: {d_id}</span>
                    </div>
                    <p style="color: var(--text-muted); font-size: 12px; margin: 0; line-height: 1.4;">{text_preview}</p>
                </div>
                """, unsafe_allow_html=True)
            with col_card_b:
                if st.button("🗑️ Delete", key=f"del_doc_{idx}", use_container_width=True):
                    docs.pop(idx)
                    st.session_state["docs"] = docs
                    _build_index_from_docs(docs)
                    st.success("Removed!")
                    st.rerun()

    # ═══════════════════════════════════════════════════════════════
    # STRUCTURED DATA EXPORT SECTION
    # ═══════════════════════════════════════════════════════════════
    if st.session_state.get("docs"):
        st.markdown("<hr style='border:none;border-top:1px solid var(--border-soft);margin:32px 0;'>", unsafe_allow_html=True)
        st.markdown("""
        <div style="margin-bottom:24px;">
            <span style="font-size:11px;font-weight:600;letter-spacing:0.08em;color:var(--text-muted);text-transform:uppercase;">DATA EXPORT</span>
            <h2 style="font-family:Outfit;font-size:22px;font-weight:700;color:var(--text-bright);margin:6px 0 4px 0;letter-spacing:-0.025em;">Structured <span style="background:linear-gradient(135deg,#8B5CF6,#3B82F6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">data export</span></h2>
            <p style="color:var(--text-muted);font-size:13px;margin:0;">Convert OCR-extracted content into canonical, machine-readable formats ready for downstream processing.</p>
        </div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;background:var(--bg-inner-card);border:1px solid var(--border-main);border-radius:12px;padding:4px;margin-bottom:20px;">
            <div style="display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:9px;background:var(--bg-card);border:1px solid var(--border-main);">
                <span style="font-size:16px;">📋</span>
                <div><div style="font-size:12px;font-weight:600;color:var(--text-bright);">JSON</div><div style="font-size:10px;color:var(--text-muted);">Nested structured</div></div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:9px;">
                <span style="font-size:16px;">📝</span>
                <div><div style="font-size:12px;font-weight:600;color:var(--text-soft);">CSV</div><div style="font-size:10px;color:var(--text-muted);">Flat spreadsheet</div></div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:9px;">
                <span style="font-size:16px;">📊</span>
                <div><div style="font-size:12px;font-weight:600;color:var(--text-soft);">Excel</div><div style="font-size:10px;color:var(--text-muted);">Multi-sheet workbook</div></div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:9px;">
                <span style="font-size:16px;">📄</span>
                <div><div style="font-size:12px;font-weight:600;color:var(--text-soft);">PDF</div><div style="font-size:10px;color:var(--text-muted);">Searchable + selectable</div></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        try:
            from structured_data import DataExtractor, JSONExporter, CSVExporter, ExcelExporter, SearchablePDFGenerator
            
            combined_doc_text = "\n\n".join([d.get("text", "") for d in st.session_state.get("docs", [])])
            first_doc_name = st.session_state["docs"][0].get("source_name", "document") if st.session_state["docs"] else "document"
            
            extractor = DataExtractor(combined_doc_text, first_doc_name)
            extracted_data = extractor.extract_all()
            export_cols = st.columns(4)
            
               # 1. JSON Card
            with export_cols[0]:
                st.markdown("""
                <div class="export-card json" style="min-height: 128px;">
                    <h4 style="color: var(--text-bright); margin: 0 0 5px 0; font-size: 15px; font-weight: 600; font-family: 'Inter', sans-serif; text-align: left !important;">📋 JSON Output</h4>
                    <p style="color: var(--text-muted); font-size: 11px; margin: 0; line-height: 1.4; font-family: 'Inter', sans-serif;">Standard internal schema containing fields, raw text, and metadata.</p>
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
                <div class="export-card csv" style="min-height: 128px;">
                    <h4 style="color: var(--text-bright); margin: 0 0 5px 0; font-size: 15px; font-weight: 600; font-family: 'Inter', sans-serif; text-align: left !important;">📝 CSV Format</h4>
                    <p style="color: var(--text-muted); font-size: 11px; margin: 0; line-height: 1.4; font-family: 'Inter', sans-serif;">Flattened spreadsheet rows, optimal for fast database imports.</p>
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
                <div class="export-card excel" style="min-height: 128px;">
                    <h4 style="color: var(--text-bright); margin: 0 0 5px 0; font-size: 15px; font-weight: 600; font-family: 'Inter', sans-serif; text-align: left !important;">📊 Excel Sheets</h4>
                    <p style="color: var(--text-muted); font-size: 11px; margin: 0; line-height: 1.4; font-family: 'Inter', sans-serif;">Professional workbook featuring frozen headers, auto-fit columns, and colored rows.</p>
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
      
            # 4. Searchable PDF Card
            with export_cols[3]:
                st.markdown("""
                <div class="export-card pdf" style="min-height: 128px;">
                    <h4 style="color: var(--text-bright); margin: 0 0 5px 0; font-size: 15px; font-weight: 600; font-family: 'Inter', sans-serif; text-align: left !important;">📄 Searchable PDF</h4>
                    <p style="color: var(--text-muted); font-size: 11px; margin: 0; line-height: 1.4; font-family: 'Inter', sans-serif;">Generates a new PDF overlaying the invisible OCR text on original images.</p>
                </div>
                """, unsafe_allow_html=True)
                ocr_pages = st.session_state.get("ocr_pages", [])
                if ocr_pages:
                    try:
                        pdf_gen = SearchablePDFGenerator()
                        pdf_bytes = pdf_gen.generate_multipage(ocr_pages)
                        st.download_button(
                            label="⬇️ Download PDF",
                            data=pdf_bytes,
                            file_name=f"{first_doc_name.replace('.pdf', '').replace('.docx', '').replace('.png', '').replace('.jpg', '').replace('.jpeg', '')}_searchable.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key="dl_searchable_pdf"
                        )
                    except Exception as exc_err:
                        st.error(f"PDF failed: {exc_err}")
                else:
                    st.button("⬇️ PDF (No OCR images)", disabled=True, use_container_width=True, key="dl_pdf_disabled")


        except Exception as e:
            st.error(f"Structured export failed: {e}")
            
def process_uploads_pipeline(uploaded_files, uploaded_images):
    pending_docs = []
    
    if uploaded_files:
        router = PDFRouter(text_threshold=100)
        for uploaded_file in uploaded_files:
            name = uploaded_file.name.lower()
            if name.endswith(".docx"):
                try:
                    uploaded_file.seek(0)
                    with st.spinner(f"Extracting text from DOCX: {uploaded_file.name}..."):
                        text = extract_text_from_docx(uploaded_file)
                    if text.strip():
                        pending_docs.append({
                            "doc_id": "",
                            "source_name": uploaded_file.name,
                            "text": text,
                        })
                        st.toast(f"Parsed DOCX: {uploaded_file.name}", icon="✅")
                except Exception as e:
                    st.error(f"DOCX extraction error ({uploaded_file.name}): {e}")
            elif name.endswith(".pdf"):
                try:
                    uploaded_file.seek(0)
                    file_bytes = uploaded_file.read()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                        tmp_pdf.write(file_bytes)
                        tmp_pdf_path = tmp_pdf.name
                    
                    with st.spinner(f"Routing and parsing PDF: {uploaded_file.name} (OCR running if scanned)..."):
                        text, processing_method, metadata = router.route_pdf(
                            tmp_pdf_path, apply_ocr=True, lang_mode=lang_mode)
                    
                    # Multi-Modal RAG: Extract and describe diagrams/tables in the PDF
                    from document_processing.multi_modal import process_pdf_multimodal
                    with st.spinner(f"Extracting and analyzing diagrams/tables from PDF..."):
                        diagram_chunks = process_pdf_multimodal(tmp_pdf_path, doc_id=uploaded_file.name)
                        if diagram_chunks:
                            diagram_text = "\n\n" + "\n\n".join([dc["text"] for dc in diagram_chunks])
                            text += diagram_text
                    
                    if text.strip():
                        pending_docs.append({
                            "doc_id": "",
                            "source_name": uploaded_file.name,
                            "text": text,
                        })
                        st.toast(f"Parsed PDF: {uploaded_file.name}", icon="✅")
                        st.caption(
                            f"{uploaded_file.name} -> "
                            f"classification: {metadata.get('classification', 'unknown')} | "
                            f"method: {processing_method} | chars: {metadata.get('char_count', 0)}"
                        )
                except Exception as e:
                    st.error(f"PDF routing error ({uploaded_file.name}): {e}")
                finally:
                    if 'tmp_pdf_path' in locals() and tmp_pdf_path:
                        try: os.unlink(tmp_pdf_path)
                        except Exception: pass
 
    if uploaded_images:
        for idx, uploaded_image in enumerate(uploaded_images):
            try:
                st.toast(f"Uploaded Image: {uploaded_image.name}", icon="📸")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
                    uploaded_image.seek(0)
                    tmp_file.write(uploaded_image.getvalue())
                    tmp_file_path = tmp_file.name
                
                with st.spinner(f"Preprocessing image and running OCR on: {uploaded_image.name}..."):
                    cleaned, preproc_preview, raw, conf = run_ocr_on_image(
                        tmp_file_path, ocr_mode, lang_mode=lang_mode, debug=True, ink_threshold=ink_threshold)
                
                pending_docs.append({
                    "doc_id": "",
                    "source_name": uploaded_image.name,
                    "text": cleaned,
                    "image_bytes": uploaded_image.getvalue(),
                })
                st.session_state["ocr_pages"].append((uploaded_image.getvalue(), cleaned))
                
                # Show image preview layout right on Page 2
                st.markdown(f"#### 📷 OCR Process: {uploaded_image.name}")
                st.image(uploaded_image, caption=f"Original File", use_container_width=True)
                if preproc_preview is not None:
                    st.image(preproc_preview, caption="Binarization & Blue Pen Removal Preview", use_container_width=True)
                
                st.subheader("Extracted Texts Details")
                st.text_area(f"Raw Text {idx}", raw or "", height=150)
                st.text_area(f"Cleaned Text {idx}", cleaned or "", height=150)
                st.metric("OCR Confidence Score", f"{conf:.1f}%")
                st.divider()
            except Exception as e:
                st.error(f"OCR error on {uploaded_image.name}: {e}")
            finally:
                if 'tmp_file_path' in locals() and tmp_file_path:
                    try: os.unlink(tmp_file_path)
                    except Exception: pass

    if pending_docs:
        col_pa, col_pb = st.columns(2)
        with col_pa:
            if st.button("⚙️ Index Uploaded Documents", use_container_width=True, key="index_uploads_pipeline_btn"):
                existing = st.session_state.get("docs", [])
                start_idx = len(existing) + 1
                for i, d in enumerate(pending_docs, start=start_idx):
                    doc = dict(d)
                    doc["doc_id"] = f"DOC_{i:03d}"
                    existing.append(doc)
                st.session_state["docs"] = existing
                _build_index_from_docs(existing)
                st.success(f"Indexed {len(existing)} document(s), {len(st.session_state.get('chunks', []))} chunk(s).")
                st.rerun()
        with col_pb:
            if st.button("🧹 Clear Ingestion Queue", use_container_width=True, key="clear_ingestion_queue_btn"):
                st.session_state["local_file_uploader"] = None
                st.session_state["local_image_uploader"] = None
                st.session_state["ocr_pages"] = []
                st.rerun()

def render_ai_assistant_centerpiece():
    docs = st.session_state.get("docs", [])
    
    # 1. Header of the AI Assistant
    col_hdr_left, col_hdr_right = st.columns([2.5, 1.2])
    with col_hdr_left:
        st.markdown("""
        <h2 style='font-family: Outfit; font-size: 1.8rem; font-weight: 700; margin-bottom: 4px; text-align: left;'>AI Assistant</h2>
        <p style='color: var(--text-muted); font-size: 13.5px; margin-bottom: 24px; text-align: left;'>Ask anything. Grounded in your documents, cited at every step.</p>
        """, unsafe_allow_html=True)
    fullscreen_active = st.session_state.get("chat_fullscreen", False)
    with col_hdr_right:
        col_m, col_n, col_p = st.columns([1.2, 1, 1.2])
        with col_m:
            model_options = ["gpt-4o"] + get_local_ollama_models()
            current_sel = st.session_state.get("hdr_model_select", "gpt-4o")
            if current_sel not in model_options:
                model_options.append(current_sel)
            st.selectbox("RAG Model", options=model_options, key="hdr_model_select", on_change=sync_model_from_hdr, label_visibility="collapsed")
        with col_n:
            if st.button("➕ New chat", use_container_width=True, key="hdr_new_chat_btn"):
                new_id = f"New chat {len(st.session_state['chat_threads']) + 1}"
                st.session_state["chat_threads"][new_id] = {
                    "time_label": "now",
                    "msg_count_label": "0 msgs",
                    "model": st.session_state.get("hdr_model_select", "gpt-4o"),
                    "temp": 0.2,
                    "top_k": 3,
                    "latency": "0.0s",
                    "cost": "$0.000",
                    "citations": [],
                    "history": []
                }
                st.session_state["active_thread_id"] = new_id
                st.rerun()
        with col_p:
            fullscreen_label = "📺 Exit Full" if fullscreen_active else "📺 Fullscreen"
            if st.button(fullscreen_label, use_container_width=True, key="hdr_fullscreen_btn"):
                st.session_state["chat_fullscreen"] = not fullscreen_active
                st.rerun()
                
    # Set active rag_mode local variable based on settings_rag_mode_ui
    rag_mode_ui = st.session_state.get("settings_rag_mode_ui", "Ollama local LLM (free)")
    if rag_mode_ui == "Local extractive (free)":
        rag_mode = "local"
    else:
        rag_mode = "ollama"
        
    st.markdown('<div class="glass-container ai-assistant-wrapper-outer" style="position: relative;">', unsafe_allow_html=True)
    st.markdown('<div class="assistant-bg-glow"></div>', unsafe_allow_html=True)
    
    if not fullscreen_active:
        left_col, center_col, right_col = st.columns([1, 2.3, 1.2])
    else:
        left_col, right_col = None, None
        center_col = st.container()
    
    threads = st.session_state["chat_threads"]
    active_id = st.session_state["active_thread_id"]
    
    if active_id not in threads and threads:
        active_id = list(threads.keys())[0]
        st.session_state["active_thread_id"] = active_id
        
    # Left Column: Conversation lists & Sync Action
    if left_col is not None:
        with left_col:
            col_conv_hdr, col_conv_add = st.columns([4, 1])
            with col_conv_hdr:
                st.markdown("<h4 style='font-family: Outfit; font-size: 14px; font-weight: 700; color: var(--text-muted); margin-bottom: 12px;'>Conversations</h4>", unsafe_allow_html=True)
            with col_conv_add:
                if st.button("➕", key="sidebar_add_chat_btn", use_container_width=True):
                    new_id = f"New chat {len(st.session_state['chat_threads']) + 1}"
                    st.session_state["chat_threads"][new_id] = {
                        "time_label": "now",
                        "msg_count_label": "0 msgs",
                        "model": st.session_state.get("hdr_model_select", "gpt-4o"),
                        "temp": 0.2,
                        "top_k": 3,
                        "latency": "0.0s",
                        "cost": "$0.000",
                        "citations": [],
                        "history": []
                    }
                    st.session_state["active_thread_id"] = new_id
                    st.rerun()
                    
            # Scrollable threads container
            for thread_id, thread in list(threads.items()):
                is_active = (thread_id == active_id)
                btn_label = f"💬 {thread_id[:24]}"
                if is_active:
                    st.button(btn_label, key=f"sel_thread_{thread_id}", type="primary", use_container_width=True)
                else:
                    if st.button(btn_label, key=f"sel_thread_{thread_id}", type="secondary", use_container_width=True):
                        st.session_state["active_thread_id"] = thread_id
                        st.rerun()
                st.markdown(f"""
                <div style="margin-left: 28px; margin-top: -24px; margin-bottom: 12px; font-size: 10.5px; color: var(--text-muted);">
                    {thread.get('time_label', 'now')} · {thread.get('msg_count_label', '0 msgs')}
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("<hr style='border-color: var(--border-soft); margin: 20px 0;' />", unsafe_allow_html=True)
            st.markdown("<h4 style='font-family: Outfit; font-size: 12px; font-weight: 700; color: var(--text-muted); margin-bottom: 10px;'>🎯 Target Focus Scope</h4>", unsafe_allow_html=True)
            
            all_doc_names = list(set(d.get("source_name") for d in docs))
            all_doc_names.sort()
            
            target_docs = st.multiselect(
                "Select target documents:",
                options=all_doc_names,
                default=[],
                label_visibility="collapsed",
                help="Select files to restrict the RAG query context. Leave empty to query everything."
            )
            
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            col_ctl1, col_ctl2 = st.columns(2)
            with col_ctl1:
                if st.button("🔄 Sync KB", use_container_width=True, key="qa_sync_btn"):
                    trigger_sync_workspace()
                    st.rerun()
            with col_ctl2:
                if st.button("🧹 Clear", use_container_width=True, key="qa_clear_btn"):
                    st.session_state["docs"] = []
                    st.session_state["chunks"] = []
                    st.session_state["vector_manager"] = None
                    st.session_state["query_history"] = []
                    st.session_state["chat_history"] = []
                    st.session_state["ocr_pages"] = []
                    st.session_state["chat_threads"] = {}
                    st.session_state["active_thread_id"] = ""
                    _init_state()
                    st.success("Cleared!")
                    st.rerun()

    # Center Column: Dynamic Dialogue & Form console
    with center_col:
        active_thread = threads.get(active_id, {
            "history": [], "model": "gpt-4o", "temp": 0.2, "top_k": 3, "latency": "0.0s", "cost": "$0.000", "citations": []
        })
        history = active_thread.get("history", [])
        
        col_chat_title, col_chat_badge = st.columns([3, 1])
        with col_chat_title:
            display_title = active_id if active_id else "New conversation"
            st.markdown(f"<h4 style='font-family: Outfit; font-size: 15px; font-weight: 700; color: var(--text-bright); margin: 0;'>{display_title}</h4>", unsafe_allow_html=True)
            st.markdown(f"<p style='color: var(--text-muted); font-size: 11px; margin: 2px 0 12px 0;'>{active_thread.get('model', 'gpt-4o')} · {len(history)} messages · {active_thread.get('latency', '0s')}</p>", unsafe_allow_html=True)
        with col_chat_badge:
            st.markdown('<span style="background-color: rgba(16, 185, 129, 0.1); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.2); padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 600; float: right; margin-top: 4px;">RAG enabled</span>', unsafe_allow_html=True)
            
        chat_height = 620 if fullscreen_active else 380
        chat_container = st.container(height=chat_height)
        
        # New Q&A Console Submission Form
        with st.form("new_qa_form", clear_on_submit=True):
            default_val = st.session_state.get("user_question", "")
            q_input = st.text_input("Ask a question about the documents:", value=default_val, key="chat_query_input", label_visibility="collapsed", placeholder="Ask anything about your documents...")
            ask_submitted = st.form_submit_button("➔")
            
        if (ask_submitted and q_input.strip()) or st.session_state.get("trigger_query", False):
            is_triggered = st.session_state.get("trigger_query", False)
            st.session_state["trigger_query"] = False
            if is_triggered:
                question_text = st.session_state.get("user_question", "")
            else:
                question_text = q_input.strip()
            st.session_state["user_question"] = ""
            
            if question_text:
                # Auto-create a new thread if none is active
                if not active_id:
                    import datetime
                    auto_id = question_text[:40].strip()
                    active_id = auto_id
                    active_thread = {
                        "history": [], "model": st.session_state.get("hdr_model_select", "gpt-4o"), "temp": 0.2,
                        "top_k": 3, "latency": "0.0s", "cost": "$0.000",
                        "citations": [], "time_label": "now", "msg_count_label": "0 msgs"
                    }
                    st.session_state["active_thread_id"] = active_id

                start_time = time.time()
                top_k_val = active_thread.get("top_k", 3)
                selected_model = active_thread.get("model", "gpt-4o")
                
                # Conversational Query Rewriting: Rewrite follow-up query using history
                from phase2.rag.rag_service import _is_overview_question, rewrite_query_with_history
                search_query = rewrite_query_with_history(
                    question_text, 
                    active_thread.get("history", []), 
                    model=selected_model
                )
                
                # Dynamically increase retrieval size for high-level/overview questions
                if _is_overview_question(search_query):
                    top_k_val = max(20, top_k_val)
                
                with st.spinner("Retrieving relevant contexts and generating answer..."):
                    retrieved_chunks = _semantic_retrieve(search_query, top_k=top_k_val, filter_docs=target_docs)
                    
                    if not retrieved_chunks:
                        ans_text = "No relevant documents found in the focus target directory. Make sure you select the correct target documents or sync the index."
                        rag_res = {
                            "question": question_text,
                            "answer": ans_text,
                            "provider": "local_extractive",
                            "elapsed_ms": 0,
                            "total_tokens_est": 0,
                            "cost_usd_est": 0.0
                        }
                        cites = []
                    else:
                        selected_model = active_thread.get("model", "gpt-4o")
                        rag_res = generate_rag_answer(
                            question=question_text,
                            retrieved_chunks=retrieved_chunks,
                            retries=2,
                            timeout_sec=60,
                            rag_mode=rag_mode,
                            model=selected_model,
                        )
                        
                        # Generate Citations metadata list
                        cites = []
                        seen_sources = set()
                        for item in retrieved_chunks:
                            src_name = item.get("source_name", item.get("doc_id", "Unknown"))
                            if src_name not in seen_sources:
                                seen_sources.add(src_name)
                                score_val = float(item.get("score", 0.0))
                                cites.append({
                                    "name": src_name,
                                    "page": str(item.get("page", 1)),
                                    "chunks": len([c for c in retrieved_chunks if c.get("source_name") == src_name]),
                                    "score": f"{score_val:.2f}"
                                })
                                
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    
                    msg_bot = {
                        "sender": "bot",
                        "text": rag_res["answer"]
                    }
                    if retrieved_chunks:
                        best_chunk = retrieved_chunks[0]
                        msg_bot["citation"] = best_chunk.get("text", "")
                        msg_bot["source"] = best_chunk.get("source_name", "document")
                        msg_bot["page"] = best_chunk.get("page", 1)
                        
                    active_thread["history"].append({"sender": "user", "text": question_text})
                    active_thread["history"].append(msg_bot)
                    active_thread["latency"] = f"{elapsed_ms / 1000:.1f}s"
                    active_thread["elapsed_ms"] = elapsed_ms
                    active_thread["cost"] = f"${rag_res.get('cost_usd_est', 0.0):.5f}"
                    active_thread["citations"] = cites
                    active_thread["msg_count_label"] = f"{len(active_thread['history'])} msgs"
                    
                    st.session_state["chat_threads"][active_id] = active_thread
                    st.session_state["latest_rag_result"] = rag_res
                    st.session_state["latest_retrieved_chunks"] = retrieved_chunks
                    st.session_state["chat_history"] = active_thread["history"]
                    
                    if retrieved_chunks:
                        st.session_state["query_history"].append({
                            "question": question_text,
                            "answer": rag_res["answer"],
                            "top_score": float(best_chunk.get("score", 0.0)),
                            "source": best_chunk.get("source_name", best_chunk.get("doc_id")),
                            "chunk_id": best_chunk.get("chunk_id"),
                        })
                st.rerun()

        with chat_container:
            if not history:
                st.markdown("""
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;padding:40px 20px;text-align:center;gap:16px;">
                    <div style="width:52px;height:52px;border-radius:14px;background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.2);display:flex;align-items:center;justify-content:center;font-size:22px;">📄</div>
                    <div>
                        <p style="color:var(--text-bright);font-size:15px;font-weight:600;margin:0 0 6px 0;font-family:Outfit;">Upload a document to get started</p>
                        <p style="color:var(--text-muted);font-size:12.5px;margin:0;line-height:1.6;max-width:280px;">Drop a PDF or image into the Document Management section above, then ask any question here.</p>
                    </div>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-top:4px;">
                        <span style="background:var(--bg-inner-card);border:1px solid var(--border-soft);color:var(--text-muted);padding:5px 12px;border-radius:99px;font-size:11px;">📋 Summarize content</span>
                        <span style="background:var(--bg-inner-card);border:1px solid var(--border-soft);color:var(--text-muted);padding:5px 12px;border-radius:99px;font-size:11px;">🔢 Extract figures</span>
                        <span style="background:var(--bg-inner-card);border:1px solid var(--border-soft);color:var(--text-muted);padding:5px 12px;border-radius:99px;font-size:11px;">👤 Find entities</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                for msg in history:
                    is_user = msg["sender"] == "user"
                    align = "right" if is_user else "left"
                    
                    if is_user:
                        import html
                        import textwrap
                        escaped_user_text = html.escape(msg['text']).replace("\n", "<br/>")
                        user_html = textwrap.dedent(f"""
                        <div style="display: flex; justify-content: flex-end; margin-bottom: 16px; width: 100%;">
                            <div style="background-color: var(--bg-chat-user); border: 1px solid var(--border-input); color: var(--text-main); padding: 12px 16px; border-radius: 12px; max-width: 80%; font-size: 13px; line-height: 1.55; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
                                <div style="font-weight: 600; font-family: Inter; font-size: 10px; color: var(--text-muted); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; text-transform: uppercase;">
                                    <span>👤</span> <span>You</span>
                                </div>
                                <div style="word-break: break-word;">{escaped_user_text}</div>
                            </div>
                        </div>
                        """).strip().replace("\n", " ")
                        st.markdown(user_html, unsafe_allow_html=True)
                    else:
                        import html
                        import textwrap
                        formatted_html = parse_markdown_to_html(msg['text'])
                        
                        citation_html = ""
                        if msg.get("citation"):
                            citation_html = f"""
                            <div class="chatgpt-cited-passage-box">
                                <div class="chatgpt-cited-passage-header">💬 CITED PASSAGE [1]</div>
                                <div class="chatgpt-cited-passage-text">"{html.escape(msg['citation'])}"</div>
                                <div class="chatgpt-cited-passage-meta">{html.escape(msg.get('source', 'document'))} · p. {msg.get('page', 1)}</div>
                            </div>
                            """
                            
                        # Format the HTML bubble using a block-level structure to prevent narrow wrap bugs
                        assistant_html = textwrap.dedent(f"""
                        <div class="chatgpt-assistant-message-wrapper">
                            <div class="chatgpt-assistant-header-row">
                                <div class="chatgpt-assistant-avatar">✨</div>
                                <div class="chatgpt-assistant-meta">
                                    <span class="chatgpt-assistant-name">SmartDoc AI Assistant</span>
                                    <span class="chatgpt-assistant-model">{html.escape(active_thread.get('model', 'gpt-4o'))}</span>
                                </div>
                            </div>
                            <div class="chatgpt-assistant-bubble">
                                {formatted_html}
                                {citation_html}
                            </div>
                            <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 6px; margin-bottom: 12px; display: flex; gap: 15px; align-items: center; font-family: Inter; user-select: none;">
                                <span>⏱️ {html.escape(active_thread.get('latency', '2.4s')) if msg == history[-1] else 'Done'}</span>
                                <span style="color: var(--text-muted); cursor: pointer; text-decoration: underline;" onclick="const bubble = this.closest('.chatgpt-assistant-message-wrapper').querySelector('.chatgpt-assistant-bubble'); const textToCopy = bubble.innerText.replace('💬 CITED PASSAGE', '').trim(); navigator.clipboard.writeText(textToCopy); this.innerText = 'Copied!'; setTimeout(() => this.innerText = 'Copy', 2000);">Copy</span>
                            </div>
                        </div>
                        """).strip().replace("\n", " ")
                        st.markdown(assistant_html, unsafe_allow_html=True)

        if history and history[-1]["sender"] == "bot":
            import textwrap
            share_html = textwrap.dedent(f"""
            <div style="font-size: 11.5px; color: var(--text-muted); margin-top: -8px; margin-bottom: 15px; display: flex; gap: 15px; align-items: center; font-family: Inter; user-select: none;">
                <span style="color: var(--text-muted); cursor: pointer; text-decoration: underline;" onclick="const el = this; el.innerText = 'Creating link...'; navigator.clipboard.writeText(window.location.href); setTimeout(() => el.innerText = 'Shared!', 500); setTimeout(() => el.innerText = 'Share', 2500);">Share</span>
            </div>
            """).strip().replace("\n", " ")
            st.markdown(share_html, unsafe_allow_html=True)
            
            col_act1, col_act2, col_act3, col_act4 = st.columns(4)
            with col_act1:
                if st.button("Draft email to CFO ↗", key="act_btn_cfo", use_container_width=True):
                    st.toast("Drafting email...")
            with col_act2:
                if st.button("Compare with Q2 ↗", key="act_btn_q2", use_container_width=True):
                    st.toast("Comparing...")
            with col_act3:
                if st.button("Export as PDF ↗", key="act_btn_pdf", use_container_width=True):
                    st.toast("Exporting PDF...")
            with col_act4:
                if st.button("Show source charts ↗", key="act_btn_charts", use_container_width=True):
                    st.toast("Opening charts...")

    # Right Column: Citations, Run Details, and Quick Prompts
    if right_col is not None:
        with right_col:
            cites = active_thread.get("citations", [])
            st.markdown(f"<h4 style='font-family: Outfit; font-size: 14px; font-weight: 700; color: var(--text-bright); margin-bottom: 2px;'>Citations</h4>", unsafe_allow_html=True)
            st.markdown(f"<p style='color: var(--text-muted); font-size: 11px; margin: 0 0 12px 0;'>{len(cites)} sources reference match</p>", unsafe_allow_html=True)
            
            if not cites:
                st.markdown("<p style='color: var(--text-muted); font-size: 11.5px; text-align: center; margin-top: 15px;'>No citation records referenced.</p>", unsafe_allow_html=True)
            else:
                for idx, cite in enumerate(cites, start=1):
                    st.markdown(f"""
                    <div class="citation-card">
                        <div>
                            <div style="font-size: 12.5px; font-weight: 600; color: var(--text-bright);">[{idx}] {cite['name'][:20]}</div>
                            <div style="font-size: 10.5px; color: var(--text-muted); margin-top: 2px;">{cite.get('chunks', 3)} chunks · p. {cite.get('page', 1)}</div>
                        </div>
                        <div style="color: #10B981; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.2); padding: 2px 6px; border-radius: 12px; font-size: 10.5px; font-weight: 700;">
                            {cite.get('score', '0.85')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
            st.markdown("<hr style='border-color: var(--border-soft); margin: 20px 0;' />", unsafe_allow_html=True)
            st.markdown(f"""
            <div class="run-details-card">
                <div class="run-details-header">
                    <span class="run-details-title">Run details</span>
                    <span class="run-details-badge">● LIVE</span>
                </div>
                <div class="run-details-grid">
                    <div class="run-detail-item">
                        <div class="run-detail-icon">🤖</div>
                        <div class="run-detail-content">
                            <div class="run-detail-label">Model</div>
                            <div class="run-detail-value model-value">{st.session_state.get('hdr_model_select', 'gpt-4o')}</div>
                        </div>
                    </div>
                    <div class="run-detail-item">
                        <div class="run-detail-icon">🌡️</div>
                        <div class="run-detail-content">
                            <div class="run-detail-label">Temperature</div>
                            <div class="run-detail-value">{active_thread.get('temp', 0.2)}</div>
                        </div>
                    </div>
                    <div class="run-detail-item">
                        <div class="run-detail-icon">🔍</div>
                        <div class="run-detail-content">
                            <div class="run-detail-label">Top-K</div>
                            <div class="run-detail-value">{active_thread.get('top_k', 8)}</div>
                        </div>
                    </div>
                    <div class="run-detail-item">
                        <div class="run-detail-icon">⚡</div>
                        <div class="run-detail-content">
                            <div class="run-detail-label">Latency</div>
                            <div class="run-detail-value latency-value">{active_thread.get('latency', '0.0s')}</div>
                        </div>
                    </div>
                    <div class="run-detail-item run-detail-cost">
                        <div class="run-detail-icon">💰</div>
                        <div class="run-detail-content">
                            <div class="run-detail-label">Cost</div>
                            <div class="run-detail-value cost-value">{active_thread.get('cost', '$0.000')}</div>
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("<hr style='border-color: var(--border-soft); margin: 20px 0;' />", unsafe_allow_html=True)
            st.markdown("<h4 style='font-family: Outfit; font-size: 14px; font-weight: 700; color: var(--text-bright); margin-bottom: 8px;'>Quick prompts</h4>", unsafe_allow_html=True)
            
            quick_prompts = [
                "📋 Generate executive summary",
                "🔢 Extract all dates & figures",
                "📅 Find action items",
                "🌐 Translate to Khmer",
                "👤 List all named entities"
            ]
            st.markdown('<div class="quick-prompts-container">', unsafe_allow_html=True)
            for q_prompt in quick_prompts:
                if st.button(q_prompt, key=f"q_prompt_{q_prompt}", use_container_width=True):
                    st.session_state["user_question"] = q_prompt.split(" ", 1)[1]
                    st.session_state["trigger_query"] = True
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom: 80px;'></div>", unsafe_allow_html=True)


def render_capabilities_section():
    st.markdown("""
    <div class="cap-section-header">
        <span class="cap-section-eyebrow">WHAT WE DO</span>
        <h2 class="cap-section-title">Core <span class="cap-gradient-text">capabilities</span></h2>
        <p class="cap-section-sub">Everything you need to extract, search, and understand your documents — powered by local AI.</p>
    </div>
    <div class="capability-grid-v2">
        <div class="capability-card-v2" style="--card-delay:0ms; --card-accent:#8B5CF6;">
            <div class="cap-glow"></div>
            <div class="cap-icon-v2">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            </div>
            <h4 class="cap-title-v2">Understand Documents</h4>
            <p class="cap-desc-v2">Extract information from PDFs, images, and scanned files using intelligent OCR with multi-language support.</p>
            <div class="cap-badge-v2" style="--badge-color:#8B5CF6;">OCR Powered</div>
        </div>
        <div class="capability-card-v2" style="--card-delay:60ms; --card-accent:#3B82F6;">
            <div class="cap-glow"></div>
            <div class="cap-icon-v2" style="color:#3B82F6;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            </div>
            <h4 class="cap-title-v2">Ask Your Knowledge</h4>
            <p class="cap-desc-v2">Search across all indexed content using semantic vector similarity — not just keyword matching.</p>
            <div class="cap-badge-v2" style="--badge-color:#3B82F6;">Semantic Search</div>
        </div>
        <div class="capability-card-v2" style="--card-delay:120ms; --card-accent:#EC4899;">
            <div class="cap-glow"></div>
            <div class="cap-icon-v2" style="color:#EC4899;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><circle cx="12" cy="12" r="10"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            </div>
            <h4 class="cap-title-v2">Grounded AI Answers</h4>
            <p class="cap-desc-v2">Generate responses backed by real evidence with inline citations — no hallucinations, fully traceable.</p>
            <div class="cap-badge-v2" style="--badge-color:#EC4899;">RAG Enabled</div>
        </div>
        <div class="capability-card-v2" style="--card-delay:180ms; --card-accent:#10B981;">
            <div class="cap-glow"></div>
            <div class="cap-icon-v2" style="color:#10B981;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            </div>
            <h4 class="cap-title-v2">Private Vector Search</h4>
            <p class="cap-desc-v2">Retrieve relevant context entirely offline using FAISS indexing — your data never leaves your machine.</p>
            <div class="cap-badge-v2" style="--badge-color:#10B981;">Local Retrieval</div>
        </div>
        <div class="capability-card-v2" style="--card-delay:240ms; --card-accent:#F59E0B;">
            <div class="cap-glow"></div>
            <div class="cap-icon-v2" style="color:#F59E0B;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>
            </div>
            <h4 class="cap-title-v2">Workflow Automation</h4>
            <p class="cap-desc-v2">Automate ingestion, indexing, and delivery pipelines with Celery background jobs and scheduled tasks.</p>
            <div class="cap-badge-v2" style="--badge-color:#F59E0B;">Background Jobs</div>
        </div>
        <div class="capability-card-v2" style="--card-delay:300ms; --card-accent:#06B6D4;">
            <div class="cap-glow"></div>
            <div class="cap-icon-v2" style="color:#06B6D4;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
            </div>
            <h4 class="cap-title-v2">Connected Integrations</h4>
            <p class="cap-desc-v2">Synchronize knowledge from Google Drive, Telegram bots, and Slack channels in real time.</p>
            <div class="cap-badge-v2" style="--badge-color:#06B6D4;">Integration Ready</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:48px'></div>", unsafe_allow_html=True)


def render_rag_pipeline_section():
    st.markdown("""
    <div class="cap-section-header" style="margin-top: 0;">
        <span class="cap-section-eyebrow">HOW IT WORKS</span>
        <h2 class="cap-section-title">RAG <span class="cap-gradient-text">pipeline</span></h2>
        <p class="cap-section-sub">From raw document to cited, grounded answer — every step runs locally on your machine.</p>
    </div>
    <div class="pipeline-v2-wrapper">
        <div class="pipeline-v2-track">
            <div class="pipeline-v2-node" style="--n:0; --nc:#8B5CF6;">
                <div class="pv2-dot">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </div>
                <div class="pv2-label">Document</div>
                <div class="pv2-sub">Source</div>
            </div>
            <div class="pipeline-v2-connector"><div class="pv2-line"></div></div>
            <div class="pipeline-v2-node" style="--n:1; --nc:#3B82F6;">
                <div class="pv2-dot" style="border-color: rgba(59,130,246,0.4); background: rgba(59,130,246,0.08);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" stroke-width="2.5"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                </div>
                <div class="pv2-label">OCR</div>
                <div class="pv2-sub">Tesseract / Paddle</div>
            </div>
            <div class="pipeline-v2-connector"><div class="pv2-line"></div></div>
            <div class="pipeline-v2-node" style="--n:2; --nc:#EC4899;">
                <div class="pv2-dot" style="border-color: rgba(236,72,153,0.4); background: rgba(236,72,153,0.08);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#EC4899" stroke-width="2.5"><line x1="21" y1="10" x2="3" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="21" y1="18" x2="9" y2="18"/></svg>
                </div>
                <div class="pv2-label">Chunking</div>
                <div class="pv2-sub">Text Splitter</div>
            </div>
            <div class="pipeline-v2-connector"><div class="pv2-line"></div></div>
            <div class="pipeline-v2-node" style="--n:3; --nc:#10B981;">
                <div class="pv2-dot" style="border-color: rgba(16,185,129,0.4); background: rgba(16,185,129,0.08);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                </div>
                <div class="pv2-label">Embeddings</div>
                <div class="pv2-sub">BGE-M3</div>
            </div>
            <div class="pipeline-v2-connector"><div class="pv2-line"></div></div>
            <div class="pipeline-v2-node" style="--n:4; --nc:#F59E0B;">
                <div class="pv2-dot" style="border-color: rgba(245,158,11,0.4); background: rgba(245,158,11,0.08);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2.5"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
                </div>
                <div class="pv2-label">FAISS</div>
                <div class="pv2-sub">Vector DB</div>
            </div>
            <div class="pipeline-v2-connector"><div class="pv2-line"></div></div>
            <div class="pipeline-v2-node" style="--n:5; --nc:#06B6D4;">
                <div class="pv2-dot" style="border-color: rgba(6,182,212,0.4); background: rgba(6,182,212,0.08);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#06B6D4" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                </div>
                <div class="pv2-label">Retrieval</div>
                <div class="pv2-sub">Semantic Query</div>
            </div>
            <div class="pipeline-v2-connector"><div class="pv2-line"></div></div>
            <div class="pipeline-v2-node" style="--n:6; --nc:#A78BFA;">
                <div class="pv2-dot" style="border-color: rgba(167,139,250,0.4); background: rgba(167,139,250,0.08);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" stroke-width="2.5"><path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/></svg>
                </div>
                <div class="pv2-label">LLM</div>
                <div class="pv2-sub">Ollama Llama3</div>
            </div>
            <div class="pipeline-v2-connector"><div class="pv2-line"></div></div>
            <div class="pipeline-v2-node pv2-final" style="--n:7; --nc:#34D399;">
                <div class="pv2-dot" style="border-color: rgba(52,211,153,0.5); background: rgba(52,211,153,0.1);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#34D399" stroke-width="2.5"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
                </div>
                <div class="pv2-label">Answer</div>
                <div class="pv2-sub">Cited · Grounded</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:48px'></div>", unsafe_allow_html=True)


def render_integrations_showcase():
    st.markdown("<p class='section-heading'>Connected services</p>", unsafe_allow_html=True)
    st.markdown("""
    <div class="integrations-grid">
        <div class="integration-card">
            <div style="font-size:22px;margin-bottom:10px;">📁</div>
            <div class="integration-name">Google Drive</div>
            <div class="integration-desc">Automated polling sync from shared cloud folders.</div>
            <span class="integration-tag">CLOUD STORAGE</span>
        </div>
        <div class="integration-card">
            <div style="font-size:22px;margin-bottom:10px;">🧬</div>
            <div class="integration-name">FAISS Vector DB</div>
            <div class="integration-desc">Local embeddings index for fast similarity lookup.</div>
            <span class="integration-tag">DATABASE</span>
        </div>
        <div class="integration-card">
            <div style="font-size:22px;margin-bottom:10px;">🧠</div>
            <div class="integration-name">Ollama LLM</div>
            <div class="integration-desc">Offline generation using local Llama3 weights.</div>
            <span class="integration-tag">GENERATIVE AI</span>
        </div>
        <div class="integration-card">
            <div style="font-size:22px;margin-bottom:10px;">🤖</div>
            <div class="integration-name">Telegram Bot</div>
            <div class="integration-desc">Real-time chat querying and document upload.</div>
            <span class="integration-tag">BOT</span>
        </div>
        <div class="integration-card">
            <div style="font-size:22px;margin-bottom:10px;">💬</div>
            <div class="integration-name">Slack Socket</div>
            <div class="integration-desc">Mention subscriptions and channel document router.</div>
            <span class="integration-tag">WORKPLACE CHAT</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:36px'></div>", unsafe_allow_html=True)


def render_system_status(metrics):
    redis_status, redis_lat    = check_redis_health()
    ollama_status, ollama_lat   = check_ollama_health()
    gdrive_status, gdrive_lat   = check_gdrive_health()
    telegram_status, telegram_lat = check_telegram_health()
    slack_status, slack_lat    = check_slack_health()
    faiss_status, faiss_lat    = check_faiss_health()

    services = [
        ("Google Drive",  gdrive_status,   metrics["gdrive_meta"],   gdrive_lat),
        ("Slack",         slack_status,    metrics["slack_meta"],    slack_lat),
        ("Telegram Bot",  telegram_status, metrics["telegram_meta"], telegram_lat),
        ("FAISS Index",   faiss_status,    f"{metrics['total_chunks']} vectors", faiss_lat),
        ("Redis Cache",   redis_status,    "Cache layer",        redis_lat),
        ("Ollama LLM",    ollama_status,   "Llama3 local",       ollama_lat),
    ]

    st.markdown("<p class='section-heading'>System status</p>", unsafe_allow_html=True)
    rows_html = ""
    for name, status, meta, latency in services:
        rows_html += f"""
        <div class="status-row">
            <div class="status-row-left">
                <span class="status-dot dot-{status}"></span>
                <span class="status-name">{name}</span>
                <span class="status-meta">{meta}</span>
            </div>
            <div style="display:flex;align-items:center;gap:14px;">
                <span style="font-size:11.5px;color:#475569;font-family:monospace;">{latency}</span>
                <span class="status-pill pill-{status}">{status}</span>
            </div>
        </div>"""
    st.markdown(f'<div class="status-table">{rows_html}</div>', unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:36px'></div>", unsafe_allow_html=True)


def render_activity_timeline_section(activities):
    import datetime

    st.markdown("<p class='section-heading'>Recent activity</p>", unsafe_allow_html=True)

    if not activities:
        st.markdown("""
        <div class="activity-feed">
            <div class="activity-row">
                <span style="font-size:13px;color:#475569;">No recent indexing activities.</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    rows_html = ""
    for act in activities:
        t_str = datetime.datetime.fromtimestamp(act["time"]).strftime("%H:%M:%S")
        text = act["text"]

        if "ocr_pdf" in text or "OCR" in text:
            icon, label = "🔍", "OCR Worker"
        elif "embed" in text.lower():
            icon, label = "🧬", "Embedding"
        elif "query" in text.lower():
            icon, label = "💬", "AI Assistant"
        elif "drive" in text.lower() or "Drive" in text:
            icon, label = "📁", "Workflow"
        else:
            icon, label = "📄", "Indexer"

        # Strip HTML tags for clean display
        import re
        clean_text = re.sub(r'<[^>]+>', '', text)
        rows_html += f"""
        <div class="activity-row">
            <div class="activity-icon">{icon}</div>
            <div class="activity-body">
                <div class="activity-title"><b>{label}</b> {clean_text[:80]}{'…' if len(clean_text) > 80 else ''}</div>
                <div class="activity-time">{t_str}</div>
            </div>
        </div>"""

    st.markdown(f'<div class="activity-feed">{rows_html}</div>', unsafe_allow_html=True)


# -----------------------------
# Main UI Execution Entrance
# -----------------------------
# Resolve logo path relative to this file (src/app.py -> ../assets/logo.png)
_LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"
st.set_page_config(
    page_title="SmartDoc AI",
    page_icon=str(_LOGO_PATH) if _LOGO_PATH.exists() else "📄",
    layout="wide"
)

_init_state()

# Inject Dynamic Theme variables block
theme = st.session_state.get("theme", "dark")
if theme == "light":
    theme_variables = """
:root {
    --bg-main: #F8FAFC;
    --bg-sidebar: #F1F5F9;
    --bg-card: #FFFFFF;
    --bg-card-hover: #F8FAFC;
    --bg-glass: rgba(255, 255, 255, 0.75);
    --border-main: rgba(0, 0, 0, 0.08);
    --border-soft: rgba(0, 0, 0, 0.05);
    --border-accent: rgba(124, 58, 237, 0.2);
    --text-main: #334155;
    --text-muted: #64748B;
    --text-bright: #0F172A;
    --text-soft: #475569;
    --text-dark: #0F172A;
    --bg-inner-card: #F8FAFC;
    --bg-inner-border: #E2E8F0;
    --bg-input: #FFFFFF;
    --border-input: rgba(0, 0, 0, 0.1);
    --bg-chat-user: #F1F5F9;
    --bg-chat-bot: transparent;
    --bg-chat-citation: #F8FAFC;
}
"""
else:
    theme_variables = """
:root {
    --bg-main: #0A0A0F;
    --bg-sidebar: #0D0D14;
    --bg-card: #12121A;
    --bg-card-hover: #1A1A28;
    --bg-glass: rgba(13, 13, 20, 0.7);
    --border-main: rgba(255, 255, 255, 0.07);
    --border-soft: rgba(255, 255, 255, 0.05);
    --border-accent: rgba(124, 58, 237, 0.18);
    --text-main: #E2E8F0;
    --text-muted: #64748B;
    --text-bright: #F8FAFC;
    --text-soft: #CBD5E1;
    --text-dark: #FAFAFA;
    --bg-inner-card: #111827;
    --bg-inner-border: #1E293B;
    --bg-input: #12121A;
    --border-input: rgba(255, 255, 255, 0.08);
    --bg-chat-user: #0F172A;
    --bg-chat-bot: transparent;
    --bg-chat-citation: #111827;
}
"""

st.markdown(f"<style>{theme_variables}</style>", unsafe_allow_html=True)

# Inject Custom Typography and Styling
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700&display=swap');

/* ─── Base ─────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], .stApp {
    background-color: var(--bg-main) !important;
    color: var(--text-main) !important;
    font-family: 'Inter', sans-serif !important;
}

/* ─── Sidebar ───────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border-soft) !important;
    width: 264px !important;
    min-width: 264px !important;
    max-width: 264px !important;
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label {
    color: var(--text-soft) !important;
}

/* ─── Chrome cleanup ────────────────────────────────── */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { background-color: transparent !important; }
.stDeployButton { display: none !important; }

/* ─── Typography ────────────────────────────────────── */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Outfit', sans-serif !important;
    color: var(--text-bright) !important;
    font-weight: 600 !important;
    letter-spacing: -0.025em !important;
    text-align: left !important;
}

/* ─── Layout ────────────────────────────────────────── */
div.block-container {
    padding-top: 2rem !important;
    padding-bottom: 4rem !important;
    padding-left: 3rem !important;
    padding-right: 3rem !important;
    max-width: 1400px !important;
}
.element-container, .stMarkdown, .stVerticalBlock {
    margin-bottom: 0 !important;
}

/* ─── Scrollbars ────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--bg-inner-border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ─── Buttons ───────────────────────────────────────── */
div.stButton > button {
    background-color: var(--bg-input) !important;
    color: var(--text-main) !important;
    border: 1px solid var(--border-input) !important;
    border-radius: 7px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    padding: 8px 16px !important;
    transition: all 0.15s ease !important;
    font-family: 'Inter', sans-serif !important;
}
div.stButton > button:hover {
    background-color: var(--bg-card-hover) !important;
    border-color: rgba(124, 58, 237, 0.3) !important;
    color: var(--text-bright) !important;
}
div.stButton > button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #7C3AED, #2563EB) !important;
    color: #FFF !important;
    border: none !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 10px rgba(124,58,237,0.3) !important;
}
div.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #8B5CF6, #3B82F6) !important;
    box-shadow: 0 4px 14px rgba(124,58,237,0.4) !important;
}

/* ─── Inputs ────────────────────────────────────────── */
div[data-baseweb="select"] > div {
    background-color: var(--bg-input) !important;
    border: 1px solid var(--border-input) !important;
    border-radius: 7px !important;
    color: var(--text-bright) !important;
    font-size: 13px !important;
}
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea {
    background-color: var(--bg-input) !important;
    border: 1px solid var(--border-input) !important;
    color: var(--text-bright) !important;
    border-radius: 7px !important;
    padding: 9px 13px !important;
    font-size: 13px !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus {
    border-color: #7C3AED !important;
    box-shadow: 0 0 0 3px rgba(124,58,237,0.15) !important;
}
/* stFileUploader wrapper card */
div[data-testid="stFileUploader"] {
    background-color: var(--bg-card) !important;
    border: 1px dashed var(--border-main) !important;
    border-radius: 10px !important;
    padding: 10px !important;
}
/* Make inner widgets/dropzones transparent so the outer bg is visible */
div[data-testid="stFileUploader"] section,
div[data-testid="stFileUploader"] div,
div[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"],
div[data-testid="stFileUploader"] [data-testid="stFileUploadDropzone"] {
    background-color: transparent !important;
    background: transparent !important;
    border: none !important;
}
/* Ensure labels and instructions match theme text color */
div[data-testid="stFileUploader"] label,
div[data-testid="stFileUploader"] p,
div[data-testid="stFileUploader"] span,
div[data-testid="stFileUploader"] small {
    color: var(--text-main) !important;
}
/* Style uploader browse files button */
div[data-testid="stFileUploader"] button {
    background-color: var(--bg-input) !important;
    border: 1px solid var(--border-input) !important;
    color: var(--text-main) !important;
    border-radius: 6px !important;
}
div[data-testid="stFileUploader"] button:hover {
    background-color: var(--bg-card-hover) !important;
    border-color: var(--border-accent) !important;
    color: var(--text-bright) !important;
}
label {
    color: var(--text-main) !important;
}
[data-testid="stSidebar"] label {
    color: var(--text-soft) !important;
}
/* Card custom overrides */
.empty-state-card {
    background-color: var(--bg-inner-card) !important;
    border: 1px solid var(--bg-inner-border) !important;
    color: var(--text-muted) !important;
    padding: 40px;
    border-radius: 8px;
    text-align: center;
    margin-top: 15px;
}
.doc-list-card {
    background-color: var(--bg-inner-card) !important;
    border: 1px solid var(--bg-inner-border) !important;
    padding: 15px;
    border-radius: 8px;
    margin-bottom: 12px;
}
.citation-card {
    background-color: var(--bg-inner-card) !important;
    border: 1px solid var(--border-input) !important;
    padding: 10px;
    border-radius: 8px;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 2px 4px rgba(0,0,0,0.15);
}
.export-card {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border-main) !important;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 8px;
    transition: border-color 0.15s ease;
}
.export-card:hover {
    border-color: var(--border-accent) !important;
}
div[data-testid="stExpander"] {
    background-color: var(--bg-input) !important;
    border: 1px solid var(--border-main) !important;
    border-radius: 10px !important;
}
div[data-testid="stDataFrame"] {
    background-color: var(--bg-input) !important;
    border: 1px solid var(--border-main) !important;
    border-radius: 8px !important;
}

/* Quick prompts modern card styling */
.quick-prompts-container div.stButton > button {
    background-color: var(--bg-inner-card) !important;
    color: var(--text-soft) !important;
    border: 1px solid var(--bg-inner-border) !important;
    border-radius: 8px !important;
    text-align: left !important;
    padding: 10px 14px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
    margin-bottom: 6px !important;
    width: 100% !important;
}

.quick-prompts-container div.stButton > button:hover {
    background-color: var(--bg-card-hover) !important;
    border-color: rgba(124, 58, 237, 0.4) !important;
    color: var(--text-bright) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(124, 58, 237, 0.08) !important;
}

.quick-prompts-container div.stButton > button:active {
    transform: translateY(1px) !important;
}

.quick-prompts-container div.stButton > button > div {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    text-align: left !important;
    width: 100% !important;
}

.quick-prompts-container div.stButton > button p {
    text-align: left !important;
    width: 100% !important;
}

/* ─── Glass container ───────────────────────────────── */
.glass-container {
    background: var(--bg-glass) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border: 1px solid var(--border-main) !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4) !important;
}

/* ─── Page header strip ─────────────────────────────── */
.page-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border-soft);
    margin-bottom: 28px;
}
.page-header-left {}
.page-eyebrow {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 4px;
}
.page-title {
    font-family: 'Outfit', sans-serif;
    font-size: 22px;
    font-weight: 700;
    color: var(--text-bright);
    margin: 0;
    letter-spacing: -0.025em;
}
.page-subtitle {
    font-size: 13px;
    color: var(--text-muted);
    margin: 4px 0 0 0;
}

/* ─── Metric cards ──────────────────────────────────── */
.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border-main);
    border-radius: 10px;
    padding: 20px 22px;
}
.metric-label {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-muted);
    letter-spacing: 0.02em;
    margin-bottom: 8px;
}
.metric-value {
    font-family: 'Outfit', sans-serif;
    font-size: 28px;
    font-weight: 700;
    color: var(--text-bright);
    letter-spacing: -0.03em;
    line-height: 1;
    margin-bottom: 6px;
}
.metric-delta {
    font-size: 11.5px;
    font-weight: 600;
    color: #10B981;
}
.metric-delta.neg { color: #EF4444; }

/* ─── Section heading ───────────────────────────────── */
.section-heading {
    font-family: 'Outfit', sans-serif;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-muted);
    letter-spacing: 0.03em;
    text-transform: uppercase;
    margin: 0 0 16px 0;
}

/* ─── System status table ───────────────────────────── */
.status-table {
    width: 100%;
    background: var(--bg-card);
    border: 1px solid var(--border-main);
    border-radius: 10px;
    overflow: hidden;
}
.status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 11px 18px;
    border-bottom: 1px solid var(--border-soft);
    font-size: 13px;
}
.status-row:last-child { border-bottom: none; }
.status-row-left {
    display: flex;
    align-items: center;
    gap: 10px;
}
.status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
}
.status-dot.dot-Healthy  { background: #10B981; box-shadow: 0 0 6px #10B981; }
.status-dot.dot-Warning  { background: #F59E0B; box-shadow: 0 0 6px #F59E0B; }
.status-dot.dot-Offline  { background: #EF4444; box-shadow: 0 0 6px #EF4444; }
.status-name { color: var(--text-soft); font-weight: 500; }
.status-meta { font-size: 11px; color: var(--text-muted); }
.status-pill {
    font-size: 11px;
    font-weight: 600;
    padding: 2px 9px;
    border-radius: 99px;
}
.status-pill.pill-Healthy  { background: rgba(16,185,129,0.12); color: #10B981; }
.status-pill.pill-Warning  { background: rgba(245,158,11,0.12); color: #F59E0B; }
.status-pill.pill-Offline  { background: rgba(239,68,68,0.12);  color: #EF4444; }

/* ─── Activity feed ─────────────────────────────────── */
.activity-feed {
    background: var(--bg-card);
    border: 1px solid var(--border-main);
    border-radius: 10px;
    overflow: hidden;
}
.activity-row {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 12px 18px;
    border-bottom: 1px solid var(--border-soft);
}
.activity-row:last-child { border-bottom: none; }
.activity-icon {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: rgba(124,58,237,0.12);
    border: 1px solid rgba(124,58,237,0.2);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    flex-shrink: 0;
    margin-top: 1px;
}
.activity-body { flex: 1; min-width: 0; }
.activity-title {
    font-size: 13px;
    color: var(--text-main);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.activity-time {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 2px;
}

/* ─── Integrations cards ────────────────────────────── */
.integrations-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
    gap: 14px;
}
.integration-card {
    background: var(--bg-card);
    border: 1px solid var(--border-main);
    border-radius: 10px;
    padding: 18px;
    transition: border-color 0.15s ease;
}
.integration-card:hover { border-color: rgba(124,58,237,0.3); }
.integration-name {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-bright);
    margin-bottom: 4px;
}
.integration-desc {
    font-size: 11.5px;
    color: var(--text-muted);
    line-height: 1.4;
    margin-bottom: 10px;
}
.integration-tag {
    font-size: 9.5px;
    font-weight: 700;
    background: rgba(124, 58, 237, 0.08);
    color: var(--text-muted);
    padding: 2px 7px;
    border-radius: 4px;
    letter-spacing: 0.04em;
}

/* ─── Capability cards ──────────────────────────────── */
.capability-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 14px;
}
.capability-card {
    background: var(--bg-card);
    border: 1px solid var(--border-main);
    padding: 22px;
    border-radius: 10px;
    transition: border-color 0.15s ease;
}
.capability-card:hover { border-color: rgba(124,58,237,0.28); }
.cap-icon { font-size: 22px; margin-bottom: 12px; }
.cap-title {
    font-family: 'Outfit', sans-serif;
    font-size: 15px;
    font-weight: 600;
    color: var(--text-bright);
    margin-bottom: 6px;
}
.cap-desc { font-size: 12.5px; color: var(--text-muted); line-height: 1.5; margin: 0; }
.cap-badge {
    display: inline-block;
    background: rgba(124,58,237,0.1);
    color: #A78BFA;
    border: 1px solid rgba(124,58,237,0.2);
    font-size: 10.5px;
    font-weight: 600;
    padding: 2px 9px;
    border-radius: 99px;
    margin-top: 14px;
}

/* ─── AI Assistant wrapper ──────────────────────────── */
.assistant-bg-glow {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    width: 100%; height: 100%;
    background: radial-gradient(circle at 30% 50%, rgba(124,58,237,0.1), transparent 60%),
                radial-gradient(circle at 70% 50%, rgba(37,99,235,0.07), transparent 60%);
    filter: blur(80px);
    pointer-events: none; z-index: 0;
}
.ai-assistant-wrapper-outer {
    border-radius: 14px !important;
    padding: 28px !important;
    margin-bottom: 40px;
}

/* ─── ChatGPT-style Chat Typography ─────────────────── */
.chatgpt-assistant-message-wrapper {
    display: block;
    margin-bottom: 20px;
    width: 100%;
}
.chatgpt-assistant-header-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
    user-select: none;
}
.chatgpt-assistant-avatar {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: linear-gradient(135deg, #7C3AED, #2563EB);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    color: white;
    box-shadow: 0 2px 6px rgba(124,58,237,0.25);
}
.chatgpt-assistant-meta {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.chatgpt-assistant-name {
    font-weight: 600;
    color: var(--text-bright);
}
.chatgpt-assistant-model {
    font-size: 9px;
    color: var(--text-muted);
    background: var(--bg-inner-card);
    border: 1px solid var(--border-soft);
    padding: 1px 6px;
    border-radius: 4px;
    text-transform: uppercase;
}
.chatgpt-assistant-bubble {
    color: var(--text-main);
    font-size: 13.5px;
    line-height: 1.6;
    word-break: break-word;
}
.chatgpt-section-header {
    font-family: 'Outfit', sans-serif !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    margin-top: 18px !important;
    margin-bottom: 8px !important;
    color: #8B5CF6 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    display: flex;
    align-items: center;
    gap: 6px;
    border-bottom: none !important;
}
.chatgpt-header-icon {
    font-size: 14px;
}
.chatgpt-list {
    margin-top: 4px !important;
    margin-bottom: 12px !important;
    padding-left: 20px !important;
    list-style-type: disc !important;
}
.chatgpt-list li {
    font-size: 13px !important;
    line-height: 1.6 !important;
    margin-bottom: 6px !important;
    color: var(--text-soft) !important;
}
.chatgpt-p {
    font-size: 13.5px !important;
    line-height: 1.6 !important;
    margin-bottom: 12px !important;
    color: var(--text-main) !important;
}
.chatgpt-inline-code {
    background-color: var(--bg-inner-card) !important;
    color: #F43F5E !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-family: 'Courier New', Courier, monospace !important;
    font-size: 12px !important;
    border: 1px solid var(--border-soft) !important;
}
.chatgpt-code-block-container {
    background-color: #1E1E2F !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 8px !important;
    margin: 12px 0 !important;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
.chatgpt-code-block-header {
    background-color: #141420 !important;
    color: #94A3B8 !important;
    padding: 6px 14px !important;
    font-size: 11px !important;
    font-family: 'Inter', sans-serif !important;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgba(255,255,255,0.05) !important;
    user-select: none;
}
.chatgpt-copy-code-btn {
    cursor: pointer;
    font-weight: 500;
    transition: color 0.15s;
}
.chatgpt-copy-code-btn:hover {
    color: #FFFFFF !important;
}
.chatgpt-code-block-container pre {
    margin: 0 !important;
    padding: 14px !important;
    overflow-x: auto !important;
    background: transparent !important;
}
.chatgpt-code-block-container code {
    color: #E2E8F0 !important;
    font-family: 'Fira Code', 'Courier New', monospace !important;
    font-size: 12.5px !important;
    line-height: 1.5 !important;
    background: transparent !important;
    padding: 0 !important;
    border: none !important;
}
.chatgpt-cited-passage-box {
    background-color: var(--bg-chat-citation) !important;
    border: 1px solid var(--border-input) !important;
    padding: 14px !important;
    border-radius: 8px !important;
    margin-top: 12px !important;
    margin-bottom: 12px !important;
    border-left: 4px solid #8B5CF6 !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
}
.chatgpt-cited-passage-header {
    font-size: 10px !important;
    font-weight: 700 !important;
    color: #8B5CF6 !important;
    letter-spacing: 0.08em !important;
    margin-bottom: 6px !important;
    text-transform: uppercase !important;
    user-select: none;
}
.chatgpt-cited-passage-text {
    font-size: 12.5px !important;
    color: var(--text-soft) !important;
    font-style: italic !important;
    margin-bottom: 8px !important;
    line-height: 1.5 !important;
}
.chatgpt-cited-passage-meta {
    font-size: 11px !important;
    color: var(--text-muted) !important;
}

/* ─── Chat thread buttons ───────────────────────────── */
div.stButton > button[key*="sel_thread_"] {
    text-align: left !important;
    justify-content: flex-start !important;
    background-color: transparent !important;
    border: 1px solid transparent !important;
    color: var(--text-muted) !important;
    font-size: 12.5px !important;
    margin-bottom: 2px !important;
}
div.stButton > button[key*="sel_thread_"]:hover {
    background-color: var(--bg-inner-card) !important;
    color: var(--text-main) !important;
}
div.stButton > button[key*="sel_thread_"][type="primary"] {
    background-color: var(--bg-inner-card) !important;
    border: 1px solid var(--border-main) !important;
    color: var(--text-bright) !important;
}

/* ─── Chat input form ───────────────────────────────── */
form[data-testid="stForm"] {
    border: 1px solid var(--border-input) !important;
    border-radius: 20px !important;
    background-color: var(--bg-input) !important;
    padding: 3px 10px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2) !important;
}
form[data-testid="stForm"] div[data-testid="stTextInput"] input {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: var(--text-bright) !important;
    font-size: 13px !important;
}
form[data-testid="stForm"] button[data-testid="stFormSubmitButton"] {
    background: #7C3AED !important;
    color: #FFF !important;
    border-radius: 50% !important;
    width: 30px !important;
    height: 30px !important;
    min-width: 30px !important;
    padding: 0 !important;
    font-size: 13px !important;
    border: none !important;
}

/* ─── Quick prompt buttons ──────────────────────────── */
div.stButton > button[key*="q_prompt_"] {
    text-align: left !important;
    justify-content: flex-start !important;
    background-color: transparent !important;
    border: none !important;
    color: var(--text-muted) !important;
    font-size: 12px !important;
    padding: 5px 0 !important;
    transition: color 0.15s !important;
    margin-bottom: 1px !important;
}
div.stButton > button[key*="q_prompt_"]:hover {
    color: #A78BFA !important;
    background-color: transparent !important;
}

/* ─── gradient text utility ─────────────────────────── */
.gradient-text {
    background: linear-gradient(135deg, #8B5CF6, #3B82F6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

/* ─── Run Details Card (modern) ─────────────────────── */
.run-details-card {
    background: linear-gradient(145deg, var(--bg-sidebar), var(--bg-main));
    border: 1px solid var(--border-accent);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 20px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04);
}
.run-details-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border-soft);
}
.run-details-title {
    font-family: 'Outfit', sans-serif;
    font-size: 13px;
    font-weight: 700;
    color: var(--text-bright);
    letter-spacing: -0.01em;
}
.run-details-badge {
    font-size: 10px;
    font-weight: 700;
    color: #10B981;
    letter-spacing: 0.04em;
    background: rgba(16,185,129,0.1);
    border: 1px solid rgba(16,185,129,0.2);
    padding: 2px 8px;
    border-radius: 99px;
    animation: blink-badge 2s ease-in-out infinite;
}
@keyframes blink-badge {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
.run-details-grid {
    display: flex;
    flex-direction: column;
    gap: 2px;
}
.run-detail-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 8px;
    transition: background 0.15s;
}
.run-detail-item:hover { background: var(--bg-inner-card); }
.run-detail-icon {
    font-size: 13px;
    width: 22px;
    text-align: center;
    flex-shrink: 0;
}
.run-detail-content { flex: 1; display: flex; justify-content: space-between; align-items: center; }
.run-detail-label { font-size: 11.5px; color: var(--text-muted); }
.run-detail-value { font-size: 12px; font-weight: 700; color: var(--text-main); font-family: 'Inter', monospace; }
.model-value { color: #A78BFA; background: rgba(167,139,250,0.08); padding: 1px 7px; border-radius: 5px; font-size: 11px; }
.latency-value { color: #34D399; }
.cost-value { color: #F59E0B; }

/* ─── Capabilities v2 ───────────────────────────────── */
.cap-section-header {
    margin-bottom: 28px;
    padding-top: 8px;
}
.cap-section-eyebrow {
    font-size: 11px;
    font-weight: 700;
    color: var(--text-muted);
    letter-spacing: 0.1em;
    text-transform: uppercase;
    display: block;
    margin-bottom: 6px;
}
.cap-section-title {
    font-family: 'Outfit', sans-serif;
    font-size: 24px;
    font-weight: 700;
    color: var(--text-bright);
    margin: 0 0 8px 0;
    letter-spacing: -0.03em;
}
.cap-section-sub {
    font-size: 13.5px;
    color: var(--text-muted);
    margin: 0;
    line-height: 1.55;
}
.capability-grid-v2 {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
}
.capability-card-v2 {
    position: relative;
    background: linear-gradient(145deg, var(--bg-card), var(--bg-sidebar));
    border: 1px solid var(--border-main);
    padding: 24px;
    border-radius: 14px;
    overflow: hidden;
    transition: border-color 0.25s ease, transform 0.2s ease, box-shadow 0.25s ease;
    animation: card-fade-in 0.5s ease both;
    animation-delay: var(--card-delay, 0ms);
    cursor: default;
}
@keyframes card-fade-in {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}
.capability-card-v2:hover {
    border-color: var(--card-accent, #8B5CF6);
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.04);
}
.capability-card-v2:hover .cap-glow {
    opacity: 1;
}
.cap-glow {
    position: absolute;
    top: -30px;
    left: -30px;
    width: 120px;
    height: 120px;
    border-radius: 50%;
    background: radial-gradient(circle, var(--card-accent, #8B5CF6) 0%, transparent 70%);
    opacity: 0;
    transition: opacity 0.3s ease;
    pointer-events: none;
    filter: blur(20px);
}
.cap-icon-v2 {
    width: 42px;
    height: 42px;
    border-radius: 10px;
    background: rgba(139,92,246,0.1);
    border: 1px solid rgba(139,92,246,0.2);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #8B5CF6;
    margin-bottom: 16px;
    transition: background 0.2s, border-color 0.2s;
}
.capability-card-v2:hover .cap-icon-v2 {
    background: rgba(139,92,246,0.18);
}
.cap-title-v2 {
    font-family: 'Outfit', sans-serif;
    font-size: 15.5px;
    font-weight: 700;
    color: var(--text-bright);
    margin: 0 0 8px 0;
    letter-spacing: -0.02em;
}
.cap-desc-v2 {
    font-size: 12.5px;
    color: var(--text-muted);
    line-height: 1.6;
    margin: 0 0 16px 0;
}
.cap-badge-v2 {
    display: inline-block;
    background: rgba(139,92,246,0.08);
    color: var(--badge-color, #A78BFA);
    border: 1px solid rgba(139,92,246,0.15);
    font-size: 10px;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 99px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}

/* ─── RAG Pipeline v2 ───────────────────────────────── */
.pipeline-v2-wrapper {
    background: linear-gradient(145deg, var(--bg-sidebar), var(--bg-card));
    border: 1px solid var(--border-main);
    border-radius: 16px;
    padding: 28px 24px;
    overflow-x: auto;
}
.pipeline-v2-track {
    display: flex;
    align-items: center;
    min-width: max-content;
    gap: 0;
}
.pipeline-v2-node {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    animation: node-in 0.4s ease both;
    animation-delay: calc(var(--n, 0) * 80ms);
}
@keyframes node-in {
    from { opacity: 0; transform: scale(0.85); }
    to { opacity: 1; transform: scale(1); }
}
.pv2-dot {
    width: 48px;
    height: 48px;
    border-radius: 14px;
    background: rgba(139,92,246,0.08);
    border: 1px solid rgba(139,92,246,0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #8B5CF6;
    transition: transform 0.2s, box-shadow 0.2s;
    position: relative;
}
.pipeline-v2-node:hover .pv2-dot {
    transform: scale(1.08);
    box-shadow: 0 0 16px rgba(139,92,246,0.25);
}
.pv2-final .pv2-dot {
    box-shadow: 0 0 20px rgba(52,211,153,0.2);
}
.pv2-label {
    font-size: 12px;
    font-weight: 700;
    color: var(--text-bright);
    font-family: 'Outfit', sans-serif;
}
.pv2-sub {
    font-size: 9.5px;
    color: var(--text-muted);
    text-align: center;
    white-space: nowrap;
}
.pipeline-v2-connector {
    flex: 1;
    min-width: 24px;
    display: flex;
    align-items: flex-start;
    padding-top: 24px;
}
.pv2-line {
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, rgba(139,92,246,0.3), rgba(59,130,246,0.3));
    position: relative;
}
.pv2-line::after {
    content: '';
    position: absolute;
    right: -4px;
    top: -3px;
    width: 7px;
    height: 7px;
    border-top: 1px solid rgba(59,130,246,0.5);
    border-right: 1px solid rgba(59,130,246,0.5);
    transform: rotate(45deg);
}
</style>
""", unsafe_allow_html=True)

_init_state()

# -----------------------------
# Sidebar Configuration Panel
# -----------------------------
# Show logo in sidebar if available
_LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"
if _LOGO_PATH.exists():
    st.sidebar.image(str(_LOGO_PATH), use_container_width=True)
st.sidebar.markdown("""
<div style="padding:8px 0 18px 0;border-bottom:1px solid var(--border-soft);margin-bottom:18px;text-align:center;">
    <span style="font-family:Outfit;font-size:17px;font-weight:800;color:var(--text-bright);letter-spacing:-0.03em;">SmartDoc AI</span><br/>
    <span style="background:rgba(124,58,237,0.12);color:#A78BFA;padding:2px 8px;border-radius:99px;font-size:9.5px;font-weight:600;letter-spacing:0.05em;border:1px solid rgba(124,58,237,0.2);display:inline-block;margin-top:4px;">
        DOCUMENT INTELLIGENCE
    </span>
</div>
""", unsafe_allow_html=True)

# Theme toggle switch
theme_mode = st.sidebar.toggle(
    "☀️ Light Theme" if st.session_state.get("theme", "dark") == "dark" else "🌙 Dark Theme",
    value=(st.session_state.get("theme", "dark") == "light"),
    key="theme_toggle_widget"
)
new_theme = "light" if theme_mode else "dark"
if new_theme != st.session_state["theme"]:
    st.session_state["theme"] = new_theme
    st.rerun()

with st.sidebar.expander("⚙️ Pipeline Configuration", expanded=False):
    st.markdown("<h4 style='font-family: Outfit; font-size: 12px; font-weight: 600; color: #94A3B8; margin-bottom: 8px;'>👁️ OCR ENGINE</h4>", unsafe_allow_html=True)
    st.radio(
        "Backend engine:",
        ("Auto", "Tesseract (fast)", "PaddleOCR (better handwriting)"),
        key="settings_ocr_mode"
    )
    
    st.radio(
        "Language model:",
        ("English (eng)", "Khmer (khm)", "Mixed (eng+khm)"),
        key="settings_ocr_lang"
    )
    
    ocr_language_temp = st.session_state.get("settings_ocr_lang", "English (eng)")
    if "khm" in ocr_language_temp or "Mixed" in ocr_language_temp:
        st.slider(
            "🖋️ Ink threshold (blue ink):",
            min_value=5,
            max_value=80,
            value=18,
            step=1,
            help="Tune threshold for morphological ink separation.",
            key="settings_ink_threshold"
        )
        
    st.markdown("<hr style='border-color: var(--border-soft); margin: 15px 0;' />", unsafe_allow_html=True)
    st.markdown("<h4 style='font-family: Outfit; font-size: 12px; font-weight: 600; color: #94A3B8; margin-bottom: 8px;'>🧩 QA & RAG PARAMS</h4>", unsafe_allow_html=True)
    st.radio(
        "Search retrieval path:",
        ("TF-IDF (baseline)", "Embeddings + FAISS"),
        key="settings_qa_mode"
    )
    
    st.radio(
        "RAG generation model:",
        ("Local extractive (free)", "Ollama local LLM (free)"),
        key="settings_rag_mode_ui",
        on_change=sync_model_from_sidebar
    )
    
    st.markdown("<hr style='border-color: var(--border-soft); margin: 15px 0;' />", unsafe_allow_html=True)
    st.markdown("<h4 style='font-family: Outfit; font-size: 12px; font-weight: 600; color: #94A3B8; margin-bottom: 8px;'>⚙️ MAINTENANCE</h4>", unsafe_allow_html=True)
    if st.button("Purge Database & History", use_container_width=True, key="settings_purge_btn"):
        st.session_state["docs"] = []
        st.session_state["chunks"] = []
        st.session_state["vector_manager"] = None
        st.session_state["query_history"] = []
        st.session_state["chat_history"] = []
        st.session_state["ocr_pages"] = []
        st.session_state["chat_threads"] = {}
        st.session_state["active_thread_id"] = ""
        _init_state()
        st.success("Shared index and history purged successfully.")
        st.rerun()

st.sidebar.markdown("""
<div style="margin-top: 30px; padding: 15px; background: var(--bg-inner-card); border: 1px solid var(--bg-inner-border); border-radius: 8px;">
    <h4 style="font-family: Outfit; color: var(--text-bright); font-size: 12px; font-weight: 600; margin: 0 0 6px 0;">Workspace Status</h4>
    <p style="color: var(--text-muted); font-size: 10.5px; margin: 0; margin-bottom: 4px;">Indexed sources: <b>{docs_len}</b></p>
    <p style="color: var(--text-muted); font-size: 10.5px; margin: 0; display: flex; align-items: center; gap: 4px;">
        FAISS database: <span style="background: rgba(16, 185, 129, 0.1); color: #10B981; padding: 1px 6px; border-radius: 8px; font-size: 9px; font-weight: 600;">Active</span>
    </p>
</div>
""".format(docs_len=len(st.session_state.get("docs", []))), unsafe_allow_html=True)

# -----------------------------
# Global Configurations Reader
# -----------------------------
ocr_mode = st.session_state.get("settings_ocr_mode", "Auto")
ocr_language = st.session_state.get("settings_ocr_lang", "English (eng)")
lang_mode = {
    "English (eng)": "eng",
    "Khmer (khm)": "khm",
    "Mixed (eng+khm)": "eng+khm",
}[ocr_language]

ink_threshold = st.session_state.get("settings_ink_threshold", 18) if "khm" in lang_mode else None

qa_mode = st.session_state.get("settings_qa_mode", "Embeddings + FAISS")
rag_mode_ui = st.session_state.get("settings_rag_mode_ui", "Ollama local LLM (free)")

if rag_mode_ui == "Local extractive (free)":
    rag_mode = "local"
else:
    rag_mode = "ollama"

# -----------------------------
# Single-Page Layout Rendering
# -----------------------------
metrics = get_dashboard_metrics()

render_hero_section(metrics)

# Two-column layout: status + activity sit beside each other on overview
col_ov_left, col_ov_right = st.columns([1, 1])
with col_ov_left:
    render_system_status(metrics)
with col_ov_right:
    render_activity_timeline_section(metrics["activities"])

st.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.06);margin:8px 0 36px 0'>", unsafe_allow_html=True)

render_ai_assistant_centerpiece()

st.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.06);margin:8px 0 36px 0'>", unsafe_allow_html=True)

render_document_management()

st.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.06);margin:8px 0 36px 0'>", unsafe_allow_html=True)

render_capabilities_section()
render_rag_pipeline_section()
render_integrations_showcase()