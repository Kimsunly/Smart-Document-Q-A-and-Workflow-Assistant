import os
import logging
from pathlib import Path
from typing import List

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from automation.config import TELEGRAM_BOT_TOKEN
from automation.tasks import ingest_and_index_file
from automation.utils import query_documents, answer_question

logger = logging.getLogger(__name__)

META_DIR = os.getenv("META_DIR", "data/index_meta")
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _recent_ingested_docs(limit: int = 8) -> List[str]:
    """Get list of recently ingested documents."""
    ingest_files = sorted(
        Path(META_DIR).glob("ingest_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    names = []
    for path in ingest_files[:limit]:
        stem = path.stem
        parts = stem.split("_", 2)
        names.append(parts[2] if len(parts) == 3 else stem)
    return names


def _help_text() -> str:
    """Return help message with all available commands."""
    return (
        "📚 <b>Smart Document Q&A Bot - Available Commands</b>\n\n"
        "<b>Query Documents:</b>\n"
        "• /ask &lt;question&gt; - Ask a question about indexed documents\n"
        "• /search &lt;topic&gt; - Search for topics/keywords (top 5 results)\n"
        "• /summarize - Generate summary of all indexed documents\n\n"
        "<b>Admin Commands:</b>\n"
        "• /list_docs - Show recently indexed files\n"
        "• /ingest_health - Check ingestion queue status\n"
        "• /help - Show this help message\n\n"
        "<b>File Upload:</b>\n"
        "Send PDF, DOCX, or TXT files and they'll be automatically indexed.\n\n"
        "<i>Tip: Use /ask, /search, /summarize with your query, e.g., /ask what is the daily schedule?</i>"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "👋 Welcome to Smart Document Q&A Bot!\n\n"
        "Send a document (PDF, DOCX, TXT) or use commands to query indexed documents.\n\n"
        "Type /help to see all available commands."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await update.message.reply_text(_help_text(), parse_mode="HTML")


async def cmd_list_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list_docs command."""
    docs = _recent_ingested_docs(limit=8)
    if not docs:
        await update.message.reply_text(
            "No indexed docs yet. Upload a file and wait for processing."
        )
        return

    lines = ["<b>Recent Indexed Documents:</b>\n"]
    for i, name in enumerate(docs, 1):
        lines.append(f"{i}. {name}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_ingest_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ingest_health command."""
    try:
        task = ingest_and_index_file.delay(
            b"", "healthcheck.txt", "telegram_health")
        await update.message.reply_text(
            f"✅ Ingestion queue reachable.\nTest task ID: <code>{task.id}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ingestion queue error: {str(e)[:100]}")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ask command."""
    if not context.args:
        await update.message.reply_text("Usage: /ask &lt;your question&gt;", parse_mode="HTML")
        return

    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Usage: /ask &lt;your question&gt;", parse_mode="HTML")
        return

    try:
        status_msg = await update.message.reply_text(
            f"🔍 Searching documents for: <b>{question}</b>\n<i>Processing...</i>",
            parse_mode="HTML",
        )

        results = query_documents(question, top_k=3)

        if not results:
            await status_msg.edit_text(f"No relevant documents found for: {question}")
            return

        context_text = "\n\n".join(
            [
                f"<b>Source:</b> {r.get('source', 'Unknown')}\n{r.get('text', '')}"
                for r in results
            ]
        )
        answer = answer_question(question, context_text)

        response = f"<b>Q:</b> {question}\n\n<b>A:</b> {answer}"
        await status_msg.edit_text(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ask command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /search command."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /search &lt;topic or keywords&gt;", parse_mode="HTML"
        )
        return

    search_query = " ".join(context.args).strip()
    if not search_query:
        await update.message.reply_text(
            "Usage: /search &lt;topic or keywords&gt;", parse_mode="HTML"
        )
        return

    try:
        status_msg = await update.message.reply_text(
            f"🔎 Searching for: <b>{search_query}</b>", parse_mode="HTML"
        )

        results = query_documents(search_query, top_k=5)

        if not results:
            await status_msg.edit_text(f"No results found for: {search_query}")
            return

        lines = ["<b>Search Results:</b>\n"]
        for i, result in enumerate(results, 1):
            source = result.get("source", "Unknown")
            score = result.get("score", 0)
            text_snippet = result.get("text", "")[:80]
            lines.append(f"{i}. <b>{source}</b> (score: {score:.2f})")
            lines.append(f"   <i>{text_snippet}...</i>\n")

        await status_msg.edit_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Search command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def cmd_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /summarize command."""
    try:
        status_msg = await update.message.reply_text(
            "⏳ <i>Generating summary of indexed documents...</i>", parse_mode="HTML"
        )

        docs = _recent_ingested_docs(limit=10)
        if not docs:
            await status_msg.edit_text("No documents indexed yet.")
            return

        summary_prompt = f"Summarize these documents briefly: {', '.join(docs)}"
        results = query_documents(summary_prompt, top_k=5)

        if results:
            context_text = "\n".join([r.get("text", "") for r in results])
            summary = answer_question(summary_prompt, context_text)
        else:
            summary = f"Indexed {len(docs)} documents: {', '.join(docs)}"

        response = f"<b>Summary of Indexed Documents:</b>\n\n{summary}"
        await status_msg.edit_text(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Summarize command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads."""
    doc = update.message.document
    if not doc:
        return

    file_name = doc.file_name or "telegram_doc"
    file_ext = Path(file_name).suffix.lower()

    if file_ext not in SUPPORTED_EXTENSIONS:
        await update.message.reply_text(
            f"❌ Unsupported file type: {file_ext}\n"
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
        return

    try:
        status_msg = await update.message.reply_text(
            f"📥 Downloading <b>{file_name}</b>...", parse_mode="HTML"
        )

        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        source_name = f"telegram:{doc.file_id}:{file_name}"
        task = ingest_and_index_file.delay(
            bytes(file_bytes), file_name, source_name)

        await status_msg.edit_text(
            f"✅ Queued <b>{file_name}</b> for indexing.\n"
            f"Task ID: <code>{task.id}</code>",
            parse_mode="HTML",
        )

        logger.info(
            "Enqueued Telegram ingestion task %s for %s (%s)",
            task.id,
            file_name,
            source_name,
        )

    except Exception as e:
        logger.error(f"Document upload error: {e}")
        await update.message.reply_text(f"❌ Error uploading file: {str(e)[:100]}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for command-like syntax without slash."""
    text = (update.message.text or "").strip().lower()

    if not text or text.startswith("/"):
        return

    if text in {"help", "help_docs"}:
        await cmd_help(update, context)
        return

    if text == "summarize":
        await cmd_summarize(update, context)
        return

    if text.startswith("ask "):
        query = text[4:].strip()
        if query:
            context.args = query.split()
            await cmd_ask(update, context)
        return

    if text.startswith("search "):
        query = text[7:].strip()
        if query:
            context.args = query.split()
            await cmd_search(update, context)
        return

    if text == "list_docs":
        await cmd_list_docs(update, context)
        return

    if text == "ingest_health":
        await cmd_ingest_health(update, context)
        return


def create_app():
    """Create and configure the Telegram bot application."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in environment")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list_docs", cmd_list_docs))
    app.add_handler(CommandHandler("ingest_health", cmd_ingest_health))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("summarize", cmd_summarize))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text_message))

    return app


def run_polling_sync():
    """Run the Telegram bot in polling mode."""
    app = create_app()
    logger.info("Starting Telegram bot (polling mode)...")
    try:
        app.run_polling(allowed_updates=["message", "update"])
    except KeyboardInterrupt:
        logger.info("Telegram bot stopped by user")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    run_polling_sync()
