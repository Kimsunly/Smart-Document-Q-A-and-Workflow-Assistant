from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from automation.config import TELEGRAM_BOT_TOKEN
from automation.tasks import ingest_and_index_file
import requests

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello — send a document to index it.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        return
    file = await context.bot.get_file(doc.file_id)
    bio = await file.download_as_bytearray()
    ingest_and_index_file.delay(bytes(bio), doc.file_name or "telegram_doc", "telegram")
    await update.message.reply_text(f"Queued {doc.file_name} for indexing.")

def run_polling():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()