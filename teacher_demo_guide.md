# 🎓 Smart Document Q&A and Workflow Assistant - Phase 2 Demo Guide

This guide is structured to help you present your project to your teacher step-by-step, highlighting all key functionalities, performance improvements, user interface details, and automation layers. It follows your official Phase 2 document and includes specific presentation script points to help you explain *what* you did and *how* it works.

---

## 📋 Pre-Demo Setup Checklist (Do this 5 minutes before)

Ensure all local processes are up and running:

> [!TIP]
> To prevent command errors or conflicts with global packages, it is highly recommended to run all commands through the virtual environment.

### Option A: Running with Virtual Environment Activated
1. **Activate the environment**:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
2. **Start Redis Broker (Docker)**:
   ```powershell
   docker start smartdoc-redis
   ```
3. **Start Celery background worker**:
   ```powershell
   celery -A src.automation.tasks worker --pool=threads -l info
   ```
4. **Pull Ollama Local Model** (If doing fully offline demo):
   ```powershell
   ollama serve
   # In another window:
   ollama pull llama3.2:3b
   ```
5. **Open Streamlit Server**:
   ```powershell
   streamlit run src/app.py
   ```
6. **Launch Integration Bots**:
   ```powershell
   python -m src.automation.bot_launcher --all
   ```

### Option B: Running without Activating (Using virtual env paths directly)
1. **Start Redis Broker (Docker)**:
   ```powershell
   docker start smartdoc-redis
   ```
2. **Start Celery background worker**:
   ```powershell
   .\.venv\Scripts\celery -A src.automation.tasks worker --pool=threads -l info
   ```
3. **Open Streamlit Server**:
   ```powershell
   .\.venv\Scripts\streamlit run src/app.py
   ```
4. **Launch Integration Bots**:
   ```powershell
   .\.venv\Scripts\python -m src.automation.bot_launcher --all
   ```

---

## 🏛️ STEP 1: OCR (English + Khmer)
*Goal: Show high-accuracy recognition of digital and scanned documents, including mixed English/Khmer scripts, ruled notebooks, and handwriting.*

### 🛠️ What to Demo:
1. **Show English OCR**:
   * Navigate to **📂 Documents & Ingestion** in the sidebar.
   * Upload an English scanned PDF or image. Point out the extracted text boxes.
2. **Show Khmer & Mixed-Language OCR**:
   * Click on **⚙️ System Config** in the sidebar.
   * Under **🧠 OCR Engine Parameters**, ensure Mixed language is set to **mixed (eng+khm)**.
   * Return to documents page and upload `data/images_for_ocr_test/kh_image_test.png`. Show the readable Khmer character translation and the **OCR Confidence Score** (e.g. `91.5%`).
3. **Show Preprocessing Before/After Improvements**:
   * Point to the **Binarization & Blue Pen Removal Preview** image on the screen.
   * Open the `debug/tesseract/` directory in your IDE. Show the step-by-step images generated during preprocessing (`gray.png`, `clahe.png`, `binary.png`, etc.) which illustrate automatic skew correction (deskewing) and upscaling.
4. **Show Automatic Detection**:
   * Drag and drop a digital PDF (`data/pdfs/digital_sample1.pdf`). Point to status:
     `digital_sample1.pdf -> classification: digital | method: native_pdf | chars: 1006` (skips OCR).
   * Ingest a scanned PDF (`data/pdfs/scanned_sample1.pdf`). Point to status:
     `scanned_sample1.pdf -> classification: scanned | method: ocr_pdf` (runs OCR).

### 🎤 Presentation Script Points (How to explain to your teacher):
> * **On the Classifier**: "Teacher, to optimize performance and prevent heavy compute overhead on digital files, we built an automatic **PDF Router**. It inspects the binary stream to count native characters. If native characters are detected, it skips OCR entirely and extracts the text natively in milliseconds using `PyMuPDF`. If no native characters are found, it automatically routes the file to our OCR engine."
> * **On Preprocessing**: "For scanned files and handwriting, standard OCR accuracy is low. To resolve this, we built a custom preprocessing pipeline. We convert the image to grayscale, use **CLAHE** to balance local contrast, auto-detect edges to correct the skew (skew correction), and apply a **binarization threshold filter**. If there is red notebook paper with blue ink margins, our threshold filter washes out the notebook lines, leaving only high-contrast text strokes for the Tesseract engine (`eng+khm`), significantly reducing our Character Error Rate (CER)."

---

## 📝 STEP 2: Text Processing & Chunking
*Goal: Show clean text normalization and layout-preserving token chunks.*

### 🛠️ What to Demo:
1. **Show Clean Extracted Text**:
   * Show that the output has normalized paragraph structure and is free from weird OCR spacing, control characters, and duplicate spaces.
2. **Show Example Chunks**:
   * Show the database logs or print screens displaying document text split into structured chunks. Note the page numbers, document IDs, and unique chunk IDs attached to each piece.

### 🎤 Presentation Script Points (How to explain to your teacher):
> * "Once the text is extracted, we normalize paragraph breaks, clean Unicode anomalies, and split the text into semantic chunks of about **800 to 1200 characters** with a sliding overlap. We tag each chunk with metadata including the original document ID, page number, and chunk index. This metadata is critical for generating precise citations later."

---

## 🗄️ STEP 3: Embeddings & Vector Index
*Goal: Show vector compilation and FAISS indexing.*

### 🛠️ What to Demo:
1. **Show Multi-Document Indexing**:
   * Demonstrate uploading 2 or 3 files. Show that the FAISS index updates in real-time, hosting embeddings for all files.
2. **Show Index Reloading**:
   * Refresh the page or click **"Sync Workspace Index"** and show that the FAISS manager reloads the vector database instantly from disk, preserving all documents.

### 🎤 Presentation Script Points (How to explain to your teacher):
> * "We convert the text chunks into **384-dimensional dense vector embeddings** using a local sentence-transformer model. We store these vectors in a local **FAISS (Facebook AI Similarity Search) index**. When the application starts or a file is synced, the FAISS Index Manager reloads the index from disk, supporting multi-document workspace scaling without recalculating embeddings from scratch."

---

## 🔎 STEP 4: Retrieval (Semantic Search)
*Goal: Demonstrate vector retrieval, similarity scores, and search validation.*

### 🛠️ What to Demo:
1. **Show Semantic Search Retrieval**:
   * Enter a query in the search bar. Show the top chunks retrieved.
2. **Show Similarity Scores**:
   * Point to the **Citations** card on the right panel. Point to the green relevance score badges (e.g., `0.32` or `0.85`).
3. **Show Exact Chunk Matching**:
   * Point out the exact chunk text displayed in the citation details that is passed to the LLM.

### 🎤 Presentation Script Points (How to explain to your teacher):
> * "Instead of simple keyword matching, we run a **top-k similarity search** on the FAISS index. When a user asks a question, we embed the query and retrieve the top chunks with the highest cosine similarity. We validated this search logic using a **golden set of questions** to ensure we retrieve the most relevant contexts, which are displayed dynamically with their similarity scores."

---

## 💡 STEP 5: RAG (Retrieval‑Augmented Generation)
*Goal: Demonstrate strict document grounding and fallback guardrails.*

### 🛠️ What to Demo:
1. **Show Grounded Answer**:
   * Ask a question about the document and show the RAG answer with inline citation tags.
2. **Show "I don't know" Guardrail**:
   * Ask a question outside the document context (e.g. *"What is the capital of Cambodia?"*).
   * Show that the model returns a polite *"I don't know"* message, proving it doesn't hallucinate.
3. **Show Telemetry Logs**:
   * Point out the latency (e.g. `2.6s`) and cost telemetry logs under the response bubble.

### 🎤 Presentation Script Points (How to explain to your teacher):
> * "We feed the retrieved chunks into a **grounding prompt** that forces the LLM to strictly base its answer on the provided text. If the information isn't in the chunks, the prompt forces the model to respond with 'I don't know'. We also calculate cost metrics and log search latencies. If the FAISS similarity score of the top chunk falls below our `RAG_FALLBACK_MIN_SCORE` threshold, the system immediately returns the extractive fallback answer without calling the LLM to prevent hallucinations and save cost."

---

## 💻 STEP 6: Streamlit Application (UI)
*Goal: Demonstrate the flagship premium 3-panel chat interface and interactive controls.*

### 🛠️ What to Demo:
1. **Explore the 3-Panel Chat Workspace**:
   * **Left Panel**: Show the concurrent conversations list, the `➕ New chat` button, and the focus target scope.
   * **Center Panel**: The interactive chat playground in the center (styled in ChatGPT-theme with section icons 💡, 🔍, 🎯 and code terminals).
   * **Right Panel**: Show the citations list, live run details, and quick prompts cards.
2. **Demonstrate Fullscreen Toggle**:
   * Click **📺 Fullscreen**. Show that the left and right panels collapse, the centerpiece stretches to 100% width, and the chat box height expands to `620px`. Click **Exit Full** to restore.
3. **Demonstrate Dynamic Model Dropdown**:
   * Click the **RAG Model** dropdown. Show the list of local Ollama models.
4. **Demonstrate Modern Prompt Cards & Auto-Clearing Form**:
   * Click on a **Quick prompt** card (e.g. *"Generate executive summary"*). Point out the smooth hover lift.
   * Submit a text query and show that the text input box is immediately cleared (using `clear_on_submit=True` form config) for a clean UI experience.

### 🎤 Presentation Script Points (How to explain to your teacher):
> * "We built a premium, responsive **3-panel chat workspace** that overrides Streamlit's default styling rules. When the user toggles **Fullscreen**, the left and right columns are bypassed (`None`), stretching the chat timeline to full width and expanding the scrollable chat container height from `380px` to `620px` to comfortably view long summaries."
> * "The model selector dropdown is connected to our **Ollama Tags Discovery API**. It dynamically reads available models from the local Ollama tags endpoint (`http://127.0.0.1:11434/api/tags`) and caches them (`@st.cache_data(ttl=60)`) to maintain speed. When a user clicks a **Quick prompt**, we override the text input form and instantly route the selected card question. The form uses `clear_on_submit` so the text box resets immediately after sending."

---

## ⚡ STEP 7: Workflow Automation (Cloud + Messaging)
*Goal: Demonstrate background document processing enqueued automatically from Google Drive and Telegram/Slack.*

### 🛠️ What to Demo:
#### A. Cloud Storage Automation
1. **Show the Drive Poller**:
   * Show the running poller window: `python -m src.automation.drive_poller`.
2. **Upload a file**:
   * Upload a PDF file (e.g. `data/pdfs/digital_sample2.pdf`) into the designated shared Google Drive folder in your browser.
3. **Real-time Ingestion**:
   * Watch the poller console output: `Downloading [filename] -> Enqueued Celery task [ID]`.
   * Watch the running **Celery worker console** process the task in the background.
   * Go to Streamlit, and click **"Sync Workspace Index"** on the documents page to sync.
   * Show that the new Google Drive file appears in the **Repository Documents** list and the **Target Documents** selection dropdown!
   * Use the **Focus Search** dropdown to select the Google Drive file, and ask a question. Show that the answer is retrieved specifically from that document.

#### B. Messaging Platform Automation
1. **Upload via Telegram**:
   * Open your Telegram bot chat window.
   * Send a test document (e.g. `data/pdfs/digital_sample2.pdf`).
   * **Highlight the Loading UX**: Point to the bot's real-time status updates:
     * `📥 Downloading digital_sample2.pdf...`
     * `⏳ Indexing digital_sample2.pdf... Time elapsed: Xs`
     * `✅ Successfully indexed digital_sample2.pdf! You can now ask questions about this document.`
2. **Ask Questions directly in chat**:
   * Send the Telegram command: `/list_docs` (shows the recently uploaded files).
   * Ask: `/ask what is the content?`
   * Show the bot running the embedding query and responding directly in the chat with the correct answer.
3. **Slack Bot alternative**:
   * Open your Slack channel and mention the bot: `@SmartDoc ask what is the status?`. Show that the same RAG search answers you directly in Slack.

### 🎤 Presentation Script Points (How to explain to your teacher):
> * "To integrate our solution into daily office workflows, we built a zero-touch background automation layer. We run an asynchronous **Google Drive poller** that listens for uploads."
> * "When a file is detected, it is enqueued into an **asynchronous Celery queue** running with a **Redis** message broker. This ensures that heavy tasks like OCR, text segmentation, embedding, and vector insertion do not block our Streamlit front-end. The Telegram and Slack bots tap into the same FAISS and Celery pipeline, letting users upload files and ask questions entirely from their chat clients."

---

## 📊 STEP 8: Structured Data Export
*Goal: Show structured table extraction and dynamic document exporting.*

### 🛠️ What to Demo:
1. **Locate Structured Export Cards**:
   * Scroll to the **Structured data export** section.
2. **Demonstrate Downloads**:
   * **JSON Card**: Click **⬇️ Download JSON** and open it.
   * **Excel Card**: Click **⬇️ Download Excel** and open it in Excel (show frozen headers, column spacing, and zebra rows).
   * **Searchable PDF Card**: Click **⬇️ Download PDF**. Open the file and copy-paste text directly to show it has active text overlays.
3. **Explain UI Cleanup**:
   * Point out that the screen is clean because we removed the extraction metrics preview tables, simplifying the screen layout for optimized performance.

### 🎤 Presentation Script Points (How to explain to your teacher):
> * "Beyond answering questions, the system turns unstructured documents into machine-readable datasets. We run a **DataExtractor** that locates tables, lists, and key-value forms."
> * "We clean the layout by bypassing screen previews, driving exports directly to optimized cards. The **Excel Exporter** uses `openpyxl` to auto-calculate cell character widths and dynamically resize columns, applying zebra striping for data records. The **Searchable PDF Generator** creates a canvas overlay of invisible OCR text positioned precisely over the scanned document image, converting flat scanned images into selectable, copyable PDFs."

---

## 📋 STEP 9: What I Will Demonstrate to My Teacher (Checklist)

During the live demo, make sure to walk through this exact checklist:
* [ ] **Demo Part 1 — OCR**: Digital vs scanned file classification and Tesseract eng+khm mixed OCR output.
* [ ] **Demo Part 2 — RAG**: FAISS index rebuild, question answering, and "I don't know" grounding check.
* [ ] **Demo Part 3 — UI (Streamlit)**: Dynamic model list loading, 📺 Fullscreen toggle, and modern quick prompts cards.
* [ ] **Demo Part 4 — Automation Layer**: Google Drive auto-poller ingestion and Telegram bot PDF upload.
* [ ] **Demo Part 5 — Structured Export**: Student list document extraction, searchable PDF download, and formatted Excel sheets.
* [ ] **Demo Part 6 — Architecture Diagram**: Showcase the generated project flow architecture PNG.

---

## 🎯 STEP 10: One‑Sentence Summary of Phase 2

Conclude your project presentation by showing this high-impact summary to your teacher:

> **"In Phase 2, I built a complete intelligent OCR ➔ RAG ➔ automation pipeline that can extract text (English & Khmer), index documents, answer questions, export structured data, and automatically ingest files from cloud storage or messaging apps."**
