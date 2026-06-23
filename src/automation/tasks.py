from celery import Celery
from pathlib import Path
import tempfile
import json
import time

from automation.config import CELERY_BROKER_URL, CELERY_BACKEND, META_DIR
from automation.utils import process_and_index_bytes


celery = Celery("auto_ingest", broker=CELERY_BROKER_URL,
                backend=CELERY_BACKEND)

# Load Windows-compatible Celery configuration
celery.config_from_object('automation.celery_config')


@celery.task(bind=True, name="automation.tasks.ingest_and_index_file")
def ingest_and_index_file(self, file_bytes: bytes, filename: str, source_name: str, lang_mode: str = "eng"):
    """Celery task wrapper that processes a file and indexes it.

    Returns metadata dict on success.
    """
    ts = int(time.time())
    try:
        result = process_and_index_bytes(
            file_bytes, filename, source_name, lang_mode=lang_mode)

        # persist a metadata record for this ingestion
        meta_path = Path(META_DIR) / f"ingest_{ts}_{filename}.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(result.get("meta", {}), f, ensure_ascii=False, indent=2)

        return {"status": "ok", "result": result}

    except Exception as e:
        return {"status": "error", "error": str(e)}
