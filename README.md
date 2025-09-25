# Smart Document Q&A and Workflow Assistant

An AI-powered assistant that enables natural language queries over document repositories. The system uses TF-IDF, embeddings, and Retrieval-Augmented Generation (RAG) to provide accurate answers, summaries, and references.

---

## 🚀 Features

- 📄 **Multi-format input**: PDF, Word, and plain text documents  
- 🔎 **Semantic search**: TF-IDF baseline + Embedding-based retrieval  
- 💬 **Natural language Q&A**: Ask questions, get direct answers with supporting references  
- 📑 **Document summaries**: Generate concise overviews of documents  
- 🌐 **Web interface**: Upload documents and interact via a simple UI  
- 🧪 **Evaluation**: Accuracy, precision, recall, F1-score, and usability metrics  

### 🔮 Future Plan (Phase 2)

- Cloud storage integration (Google Drive, Dropbox)  
- Workflow automation (Slack, Zapier, n8n)  
- Multi-hop reasoning for complex queries  
- Visual explainability (highlighting evidence in the document)  

---

## 📂 Project Structure

```
Smart-Doc-QA/
│── data/               # Sample datasets / documents
│── notebooks/          # Prototyping & experiments
│── src/                # Source code
│   ├── preprocessing/  # Text extraction, OCR, chunking
│   ├── retrieval/      # TF-IDF, embeddings, vector search
│   ├── rag/            # Retrieval-Augmented Generation pipeline
│   ├── webapp/         # Streamlit/Flask web interface
│   └── utils/          # Helper functions
│── tests/              # Unit tests
│── requirements.txt    # Dependencies
│── README.md           # Project overview
│── demo.mp4            # Demo video (optional)
```

---

## ⚙️ Installation

Clone the repository:

```bash
git clone https://github.com/your-username/smart-doc-qa.git
cd smart-doc-qa
```

Create a virtual environment and install requirements:

```bash
python -m venv venv
# Linux/Mac
source venv/bin/activate
# Windows
venv\Scripts\activate
pip install -r requirements.txt
```

Set up API keys (for OpenAI / Hugging Face):

```bash
export OPENAI_API_KEY=your_api_key
```

---

## ▶️ Usage

Start the web interface:

```bash
streamlit run src/webapp/app.py
```

1. Upload documents (PDF, Word, or TXT)  
2. Ask questions in natural language  
3. Get:  
   - Direct answers  
   - Supporting references  
   - Optional summaries  

---

## 🧰 Tech Stack

- **Languages:** Python, JavaScript (optional for frontend)  
- **NLP/ML:** scikit-learn, spaCy, Hugging Face Transformers  
- **AI Integration:** LangChain, LlamaIndex, OpenAI API  
- **Web:** Streamlit / Flask / FastAPI  
- **Deployment:** Heroku / Render / GitHub Pages  
- **Future (Phase 2):** Zapier, n8n, Google Drive, Slack integration  

---

## 📊 Evaluation Metrics

- **Model Performance:** Accuracy, Precision, Recall, F1-score  
- **System Usability:** User satisfaction, interface intuitiveness  
- **Efficiency:** Response time, indexing speed, resource use  

---

## 📅 Timeline (Phase 1 – MVP)

- Week 1–2: Requirement Analysis  
- Week 3–6: Model Development (TF-IDF → Embeddings → RAG)  
- Week 7–9: Web UI + Integration  
- Week 12–13: Testing & Evaluation  
- Week 14–16: Documentation + Final Report  

*(Phase 2 – Future: Workflow automation, cloud integration, advanced reasoning)*

---

## 🙌 Contributors

- Ly Kimsun (ITE, RUPP, Year 3)  
- Advisor: Mr. Toem Theara  

---

## 📜 License

MIT License 
