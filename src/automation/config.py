import os
from pathlib import Path

# Basic configuration for automation components (read from environment)

BASE_DIR = Path(__file__).resolve().parents[2]

REDIS_URL = os.getenv("AUTOMATION_REDIS_URL", "redis://localhost:6379/0")

# FAISS index and metadata storage
DATA_DIR = Path(os.getenv("AUTOMATION_DATA_DIR", str(BASE_DIR / "data")))
FAISS_INDEX_PATH = DATA_DIR / "faiss" / "auto_index"
META_DIR = DATA_DIR / "index_meta"

# Slack
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Dropbox
DROPBOX_TOKEN = os.getenv("DROPBOX_TOKEN", "")

# Google
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

# Celery
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_BACKEND = os.getenv("CELERY_BACKEND", REDIS_URL)

# ensure directories
DATA_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
