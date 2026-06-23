import os
import logging
import re
from pathlib import Path
from typing import List

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from automation.config import (
    META_DIR,
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
    SLACK_SIGNING_SECRET,
    SLACK_TOKEN_VERIFICATION_ENABLED,
)
from automation.tasks import ingest_and_index_file
from automation.utils import query_documents, answer_question

logger = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_BYTES = int(os.getenv("SLACK_MAX_FILE_BYTES", str(50 * 1024 * 1024)))


def _validate_slack_config(require_app_token: bool = False):
    missing = []
    if not SLACK_BOT_TOKEN:
        missing.append("SLACK_BOT_TOKEN")
    if not SLACK_SIGNING_SECRET:
        missing.append("SLACK_SIGNING_SECRET")
    if require_app_token and not SLACK_APP_TOKEN:
        missing.append("SLACK_APP_TOKEN")
    if missing:
        raise RuntimeError(f"Missing Slack env vars: {', '.join(missing)}")


def _is_supported_file(name: str, mimetype: str) -> bool:
    ext = Path(name or "").suffix.lower()
    if ext in SUPPORTED_EXTENSIONS:
        return True
    return (mimetype or "").startswith("text/")


def _download_private_file(url: str) -> bytes:
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    response = requests.get(url, headers=headers, timeout=120)
    response.raise_for_status()
    return response.content


def _recent_ingested_docs(limit: int = 8) -> List[str]:
    import json
    ingest_files = sorted(
        Path(META_DIR).glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    names = []
    for path in ingest_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            channel = meta.get("channel", "") or meta.get("doc_id", "")
            if channel.startswith("slack:"):
                src_name = meta.get("source_name", "")
                if src_name:
                    names.append(src_name)
                    if len(names) >= limit:
                        break
        except Exception:
            continue
    return names


def _help_text() -> str:
    return (
        "*📚 Smart Document Q&A Bot - Available Commands*\n\n"
        "*Query Documents:*\n"
        "• `ask [question]` - Ask a question about indexed documents\n"
        "• `ask [doc_name] | [question]` - Ask a question about a specific document only\n"
        "• `search [topic]` - Search for topics/keywords in documents (returns top 5 results)\n"
        "• `summarize` - Generate a summary of all indexed documents\n\n"
        "*Admin Commands:*\n"
        "• `list_docs` - Show recently indexed files\n"
        "• `ingest_health` - Check if ingestion queue is working\n"
        "• `help` or `help_docs` - Show this help message\n\n"
        "*File Upload:*\n"
        "Upload PDF, DOCX, or TXT files to any channel and the bot will automatically index them.\n\n"
        "_Tip: In Slack, mention the bot and send one of the commands above, for example: `@Smart Document ask what is the daily schedule?`._\n"
        "_To query a specific file: `@Smart Document ask Daily Schedule | what is the schedule?`_"
    )


def _normalize_command_text(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("/"):
        cleaned = cleaned[1:].strip()
    return cleaned


def _extract_command_from_message(text: str, bot_user_id: str = "") -> str:
    cleaned = (text or "").strip()
    if bot_user_id:
        cleaned = re.sub(rf"<@{re.escape(bot_user_id)}>\s*", "", cleaned).strip()
    cleaned = re.sub(r"^<@[^>]+>\s*", "", cleaned).strip()
    return _normalize_command_text(cleaned)


def _handle_text_command(text: str, respond) -> bool:
    cleaned = _normalize_command_text(text)
    if not cleaned:
        respond(_help_text())
        return True

    lowered = cleaned.lower()

    if lowered in {"help", "help_docs"}:
        respond(_help_text())
        return True

    if lowered == "summarize":
        docs = _recent_ingested_docs(limit=10)
        if not docs:
            respond("No documents indexed yet.")
            return True

        summary_prompt = f"Summarize these documents briefly: {', '.join(docs)}"

        # Pull chunks from each recent document directly so the newest upload
        # is included instead of relying on a single semantic search query.
        collected = []
        seen_sources = set()
        for doc_name in docs:
            for result in query_documents(doc_name, top_k=3, channel="slack"):
                source = result.get("source", "Unknown")
                if source in seen_sources:
                    continue
                seen_sources.add(source)
                collected.append(result)

        if collected:
            context = "\n\n".join([r.get("text", "") for r in collected])
            summary = answer_question(summary_prompt, context, channel="slack")
        else:
            summary = f"Indexed {len(docs)} documents: {', '.join(docs)}"

        respond(f"*Summary of Indexed Documents:*\n\n{summary}")
        return True

    for prefix in ("ask ", "search "):
        if lowered.startswith(prefix):
            query = cleaned[len(prefix):].strip()
            if not query:
                respond(f"Usage: {prefix.strip()} [query]")
                return True

            if prefix.startswith("ask"):
                source_filter = None
                query_text = query
                if "|" in query:
                    parts = query.split("|", 1)
                    source_filter = parts[0].strip()
                    query_text = parts[1].strip()

                results = query_documents(query_text, top_k=3, source_filter=source_filter, channel="slack")
                if not results:
                    filter_text = f" matching filter '{source_filter}'" if source_filter else ""
                    respond(f"No relevant documents found{filter_text} for: {query_text}")
                    return True

                context = "\n\n".join([
                    f"Source: {r.get('source', 'Unknown')}\n{r.get('text', '')}"
                    for r in results
                ])
                answer = answer_question(query_text, context, source_filter=source_filter, channel="slack")
                respond(f"*Q:* {query_text}\n\n*A:* {answer}")
                return True

            results = query_documents(query, top_k=5, channel="slack")
            if not results:
                respond(f"No results found for: {query}")
                return True

            lines = ["*Search Results:*"]
            for i, result in enumerate(results, 1):
                source = result.get("source", "Unknown")
                score = result.get("score", 0)
                text_snippet = result.get("text", "")[:100]
                lines.append(f"\n{i}. *{source}* (score: {score:.2f})")
                lines.append(f"   _{text_snippet}..._")

            respond("\n".join(lines))
            return True

    return False


def create_app() -> App:
    _validate_slack_config(require_app_token=False)
    app = App(
        token=SLACK_BOT_TOKEN,
        signing_secret=SLACK_SIGNING_SECRET,
        token_verification_enabled=SLACK_TOKEN_VERIFICATION_ENABLED,
    )

    @app.event("file_shared")
    def handle_file_shared(event, client, logger):
        try:
            file_id = event.get("file_id") or event.get("file", {}).get("id")
            if not file_id:
                return

            info = client.files_info(file=file_id)
            file_info = info.get("file", {})
            file_name = file_info.get("name", f"slack_{file_id}")
            mime_type = file_info.get("mimetype", "")
            size = int(file_info.get("size") or 0)
            private_url = file_info.get(
                "url_private_download") or file_info.get("url_private")

            if not _is_supported_file(file_name, mime_type):
                logger.info("Skip unsupported Slack file: %s (%s)",
                            file_name, mime_type)
                return

            if size > MAX_FILE_BYTES:
                logger.warning(
                    "Skip large Slack file %s (%s bytes)", file_name, size)
                return

            if not private_url:
                logger.warning(
                    "No private download URL for Slack file %s", file_name)
                return

            file_bytes = _download_private_file(private_url)
            # Use a unique source name that includes the Slack file id to
            # avoid collisions when multiple uploads have the same filename.
            source_name = f"slack:{file_id}:{file_name}"
            task = ingest_and_index_file.delay(file_bytes, file_name, source_name)
            logger.info("Enqueued Slack ingestion task %s for %s (%s)",
                        task.id, file_name, source_name)

        except requests.RequestException as e:
            logger.error("Slack file download error: %s", e)
        except SlackApiError as e:
            logger.error("Slack API error: %s", e)
        except Exception as e:
            logger.exception("Unexpected Slack file handler error: %s", e)

    @app.command("/list_docs")
    def cmd_list_docs(ack, respond):
        ack()
        docs = _recent_ingested_docs(limit=8)
        if not docs:
            respond(
                "No indexed docs yet. Upload a file to Slack and wait for processing.")
            return
        lines = [f"{i + 1}. {name}" for i, name in enumerate(docs)]
        respond("Recent indexed docs:\n" + "\n".join(lines))

    @app.command("/ingest_health")
    def cmd_ingest_health(ack, respond):
        ack()
        try:
            celery_ok = ingest_and_index_file.delay(
                b"", "healthcheck.txt", "slack_health")
            respond(f"Ingestion queue reachable. Test task id: {celery_ok.id}")
        except Exception as e:
            respond(f"Ingestion queue error: {e}")

    @app.command("/help")
    def cmd_help(ack, respond):
        ack()
        respond(_help_text())

    @app.command("/help_docs")
    def cmd_help_docs(ack, respond):
        ack()
        respond(_help_text())

    @app.command("/ask")
    def cmd_ask(ack, body, respond):
        ack()
        user_question = body.get("text", "").strip()
        if not user_question:
            respond("Usage: /ask [your question] OR /ask [doc_name] | [your question]")
            return

        try:
            source_filter = None
            query_text = user_question
            if "|" in user_question:
                parts = user_question.split("|", 1)
                source_filter = parts[0].strip()
                query_text = parts[1].strip()

            filter_info = f" (filtered by: *{source_filter}*)" if source_filter else ""
            respond(
                f"Searching documents for: *{query_text}*{filter_info}\n_Processing..._")

            # Query FAISS index for relevant documents
            results = query_documents(query_text, top_k=3, source_filter=source_filter, channel="slack")

            if not results:
                filter_text = f" matching filter '{source_filter}'" if source_filter else ""
                respond(f"No relevant documents found{filter_text} for: {query_text}")
                return

            # Build context from search results
            context = "\n\n".join([
                f"Source: {r.get('source', 'Unknown')}\n{r.get('text', '')}"
                for r in results
            ])

            # Generate answer using RAG
            answer = answer_question(query_text, context, source_filter=source_filter, channel="slack")

            respond(f"*Q:* {query_text}\n\n*A:* {answer}")
        except Exception as e:
            logger.error(f"Ask command error: {e}")
            respond(f"Error processing question: {str(e)[:100]}")

    @app.command("/search")
    def cmd_search(ack, body, respond):
        ack()
        search_query = body.get("text", "").strip()
        if not search_query:
            respond("Usage: /search [topic or keywords]")
            return

        try:
            respond(f"Searching for: *{search_query}*")

            # Query FAISS index
            results = query_documents(search_query, top_k=5, channel="slack")

            if not results:
                respond(f"No results found for: {search_query}")
                return

            # Format results
            lines = ["*Search Results:*"]
            for i, result in enumerate(results, 1):
                source = result.get("source", "Unknown")
                score = result.get("score", 0)
                text = result.get("text", "")[:100]
                lines.append(f"\n{i}. *{source}* (score: {score:.2f})")
                lines.append(f"   _{text}..._")

            respond("\n".join(lines))
        except Exception as e:
            logger.error(f"Search command error: {e}")
            respond(f"Error searching documents: {str(e)[:100]}")

    @app.command("/summarize")
    def cmd_summarize(ack, respond):
        ack()
        try:
            respond("_Generating summary of indexed documents..._")

            # Get all recent documents
            docs = _recent_ingested_docs(limit=10)
            if not docs:
                respond("No documents indexed yet.")
                return

            # Create a summary query
            summary_prompt = f"Summarize these documents briefly: {', '.join(docs)}"

            # Query documents to get context
            results = query_documents(summary_prompt, top_k=5, channel="slack")

            if results:
                context = "\n".join([r.get("text", "") for r in results])
                summary = answer_question(summary_prompt, context, channel="slack")
            else:
                summary = f"Indexed {len(docs)} documents: {', '.join(docs)}"

            respond(f"*Summary of Indexed Documents:*\n\n{summary}")
        except Exception as e:
            logger.error(f"Summarize command error: {e}")
            respond(f"Error generating summary: {str(e)[:100]}")

    @app.event("app_mention")
    def handle_app_mention(event, say, logger):
        bot_user_id = event.get("bot_id", "")
        text = _extract_command_from_message(event.get("text", ""), bot_user_id)

        if _handle_text_command(text, say):
            return

        say(_help_text())

    return app


def run_socket_mode():
    _validate_slack_config(require_app_token=True)
    app = create_app()
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    run_socket_mode()
