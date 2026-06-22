# Bot Integration Guide

## Overview

This project includes two integrated bots for querying indexed documents:
- **Slack Bot**: Uses Socket Mode (real-time)
- **Telegram Bot**: Uses Polling (periodically checks for updates)

Both bots share the same core functionality:
- File ingestion (PDF, DOCX, TXT)
- Document search via vector embeddings
- Q&A with LLM generation
- Command interface

## Prerequisites

Before running any bot, ensure these services are running:

1. **Redis** (Celery broker):
   ```powershell
   docker run -d -p 6379:6379 --name smartdoc-redis redis:7-alpine
   ```

2. **Celery Worker** (background task processing):
   ```powershell
   cd <project-root>
   .\.venv\Scripts\activate
   celery -A src.automation.tasks worker --pool=threads -l info
   ```

3. **Ollama LLM** (local LLM for Q&A):
   - Download Ollama from [ollama.ai](https://ollama.ai)
   - Run: `ollama serve`
   - In another terminal, pull model: `ollama pull llama3.2:3b`

## Environment Setup

Update `.env` file with bot tokens:

```env
# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

# Telegram
TELEGRAM_BOT_TOKEN=...

# Other
OLLAMA_BASE_URL=http://127.0.0.1:11434
REDIS_URL=redis://localhost:6379/0
```

## Running the Bots

### Option 1: Run Slack Bot Only
```powershell
python -m src.automation.bot_launcher --slack
```

### Option 2: Run Telegram Bot Only
```powershell
python -m src.automation.bot_launcher --telegram
```

### Option 3: Run Both Bots (Separate Processes)
```powershell
python -m src.automation.bot_launcher --all
```

### Option 4: Run with Default (Slack)
```powershell
python -m src.automation.bot_launcher
```

## Bot Commands

### Slack Bot
| Command | Usage | Example |
|---------|-------|---------|
| `/ask` | Ask question about documents | `/ask What is the daily schedule?` |
| `/search` | Search for topics (top 5 results) | `/search budget report` |
| `/summarize` | Summarize all indexed documents | `/summarize` |
| `/list_docs` | Show recently indexed files | `/list_docs` |
| `/ingest_health` | Check ingestion queue status | `/ingest_health` |
| `/help` | Show help message | `/help` |
| File Upload | Upload PDF/DOCX/TXT | Drag & drop in channel |

**Note**: Slack commands also work via mentions:
```
@Smart Document ask what is the budget?
```

Or without slash:
```
ask what is the budget?
```

### Telegram Bot
Same commands as Slack, but via Telegram:
```
/ask What is the daily schedule?
/search budget report
/summarize
/list_docs
/ingest_health
/help
```

Or without slash (natural text):
```
ask what is the budget?
search budget report
summarize
```

**File Upload**: Simply send a PDF, DOCX, or TXT file to the bot.

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   Slack Bot     │         │  Telegram Bot   │
├─────────────────┤         ├─────────────────┤
│ Socket Mode     │         │ Polling         │
│ (Real-time)     │         │ (Periodic)      │
└────────┬────────┘         └────────┬────────┘
         │                          │
         └──────────────┬───────────┘
                        │
                   ┌────▼────────────────┐
                   │  Shared Utils       │
                   ├─────────────────────┤
                   │ • query_documents() │
                   │ • answer_question() │
                   │ • ingest_files()    │
                   └────┬─────────────────┘
                        │
         ┌──────────────┼──────────────┐
         │              │              │
    ┌────▼────┐  ┌─────▼─────┐  ┌────▼────┐
    │  FAISS  │  │  Celery   │  │ Ollama  │
    │ Vector  │  │  Queue    │  │  LLM    │
    │ Index   │  │  (Redis)  │  │         │
    └─────────┘  └───────────┘  └─────────┘
```

## Features

### Document Processing
- **PDF**: Automatic routing (scanned/text) with OCR fallback
- **DOCX**: Direct text extraction
- **TXT**: Raw text ingestion

### Vector Search
- Embeddings: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim)
- Index: FAISS (IP similarity)
- Results: Top-K with similarity scores

### Q&A Generation
- **Model**: Ollama `llama3.2:3b` (3B parameters)
- **Method**: Retrieval-Augmented Generation (RAG)
- **Sources**: Includes source attribution in responses

### Background Processing
- **Queue**: Redis (via Celery)
- **Workers**: Thread pool (Windows-compatible)
- **Ingestion**: Async with task tracking

## Troubleshooting

### Bot Not Responding
1. Check Redis is running: `redis-cli ping`
2. Check Celery worker output
3. Verify bot tokens in `.env`
4. Check internet connection (for Telegram)

### "No relevant documents found"
- Upload documents first using `/list_docs`
- Wait for ingestion to complete (check Celery logs)
- Try different search terms

### Ollama Connection Error
- Ensure Ollama service is running: `ollama serve`
- Verify URL matches `OLLAMA_BASE_URL` in `.env`
- Check firewall rules

### Token Issues
- **Slack**: Regenerate bot/app tokens in Slack workspace settings
- **Telegram**: Create bot via BotFather (@BotFather on Telegram)

## Files

- `src/automation/slack_bot.py` - Slack bot implementation (Socket Mode)
- `src/automation/telegram_bot.py` - Telegram bot implementation (Polling)
- `src/automation/bot_launcher.py` - Bot launcher with CLI
- `src/automation/utils.py` - Shared utilities (search, Q&A, ingestion)
- `src/automation/tasks.py` - Celery task definitions
- `src/automation/config.py` - Configuration and environment variables

## Performance Tips

1. **Increase Celery workers**: For high-volume ingestion, scale up worker threads
2. **Cache embeddings**: FAISS index is persisted; no regeneration needed
3. **Batch uploads**: Upload multiple documents at once for efficiency
4. **Monitor queue**: Use `/ingest_health` to track pending tasks

## Next Steps

- Set up production monitoring and logging
- Add structured export (JSON/CSV/Excel)
- Implement rate limiting
- Add user authentication per platform
- Create admin dashboard
