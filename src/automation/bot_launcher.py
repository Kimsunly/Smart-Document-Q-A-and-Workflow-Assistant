"""
Bot launcher - Run Slack, Telegram, or both bots.

Usage:
    python -m src.automation.bot_launcher --slack       # Run Slack bot only
    python -m src.automation.bot_launcher --telegram    # Run Telegram bot only
    python -m src.automation.bot_launcher --all         # Run both bots (separate processes)
    python -m src.automation.bot_launcher               # Default: run Slack bot
"""

import argparse
import logging
import os
import sys
import subprocess
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def validate_environment():
    """Validate required environment variables."""
    from automation.config import SLACK_BOT_TOKEN, TELEGRAM_BOT_TOKEN

    slack_ok = bool(SLACK_BOT_TOKEN)
    telegram_ok = bool(TELEGRAM_BOT_TOKEN)

    if not slack_ok and not telegram_ok:
        logger.error(
            "❌ No bot tokens configured. Set SLACK_BOT_TOKEN and/or TELEGRAM_BOT_TOKEN in .env"
        )
        sys.exit(1)

    return slack_ok, telegram_ok


def run_slack_bot():
    """Run Slack bot (Socket Mode)."""
    logger.info("=" * 60)
    logger.info("🚀 Starting Slack Bot (Socket Mode)...")
    logger.info("=" * 60)

    from automation.slack_bot import run_socket_mode

    try:
        run_socket_mode()
    except KeyboardInterrupt:
        logger.info("Slack bot stopped by user.")
    except Exception as e:
        logger.error(f"Slack bot error: {e}")
        sys.exit(1)


def run_telegram_bot():
    """Run Telegram bot (Polling)."""
    logger.info("=" * 60)
    logger.info("🚀 Starting Telegram Bot (Polling)...")
    logger.info("=" * 60)

    from automation.telegram_bot import run_polling_sync

    try:
        run_polling_sync()
    except KeyboardInterrupt:
        logger.info("Telegram bot stopped by user.")
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")
        sys.exit(1)


def run_both_bots():
    """Run both bots in separate subprocesses."""
    logger.info("=" * 60)
    logger.info("🚀 Starting both Slack and Telegram bots...")
    logger.info("=" * 60)

    slack_process = None
    telegram_process = None

    try:
        # Run Slack bot in subprocess
        slack_process = subprocess.Popen(
            [sys.executable, "-m", "src.automation.slack_bot"],
            cwd=Path(__file__).parent.parent.parent,
        )
        logger.info(f"✅ Slack bot started (PID: {slack_process.pid})")

        # Run Telegram bot in subprocess
        telegram_process = subprocess.Popen(
            [sys.executable, "-c",
                "from src.automation.telegram_bot import run_polling_sync; run_polling_sync()"],
            cwd=Path(__file__).parent.parent.parent,
        )
        logger.info(f"✅ Telegram bot started (PID: {telegram_process.pid})")

        logger.info("=" * 60)
        logger.info("Both bots are running. Press Ctrl+C to stop.")
        logger.info("=" * 60)

        slack_process.wait()
        telegram_process.wait()

    except KeyboardInterrupt:
        logger.info("\n⏹️  Stopping both bots...")
        if slack_process:
            slack_process.terminate()
            slack_process.wait()
        if telegram_process:
            telegram_process.terminate()
            telegram_process.wait()
        logger.info("Both bots stopped.")
    except Exception as e:
        logger.error(f"Error running bots: {e}")
        if slack_process:
            slack_process.terminate()
        if telegram_process:
            telegram_process.terminate()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Run Smart Document Q&A bots (Slack, Telegram, or both)"
    )
    parser.add_argument(
        "--slack",
        action="store_true",
        help="Run Slack bot only",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Run Telegram bot only",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run both bots (in separate processes)",
    )

    args = parser.parse_args()

    slack_available, telegram_available = validate_environment()

    # Determine which bot(s) to run
    run_slack = args.slack or (not args.telegram and not args.all)
    run_telegram = args.telegram

    if args.all:
        run_slack = slack_available
        run_telegram = telegram_available
        if not run_slack and not run_telegram:
            logger.error("❌ No bots available to run.")
            sys.exit(1)

        run_both_bots()
        return

    if run_slack and not slack_available:
        logger.error(
            "❌ Slack bot token not configured (SLACK_BOT_TOKEN missing).")
        sys.exit(1)

    if run_telegram and not telegram_available:
        logger.error(
            "❌ Telegram bot token not configured (TELEGRAM_BOT_TOKEN missing).")
        sys.exit(1)

    if run_slack:
        run_slack_bot()
    elif run_telegram:
        run_telegram_bot()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
