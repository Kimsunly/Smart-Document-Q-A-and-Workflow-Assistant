"""
Google Drive poller: watches a folder for new files and enqueues ingestion tasks.
"""
import os
import json
import time
from pathlib import Path
from typing import Dict, List
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

from automation.config import GOOGLE_CREDENTIALS_JSON, META_DIR
from automation.tasks import ingest_and_index_file

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
POLLER_STATE_FILE = Path(META_DIR) / "drive_poller_state.json"


def _build_service():
    """Build Google Drive API client from service account."""
    if not GOOGLE_CREDENTIALS_JSON or not Path(GOOGLE_CREDENTIALS_JSON).exists():
        raise FileNotFoundError(f"Google credentials not found: {GOOGLE_CREDENTIALS_JSON}")
    
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_JSON, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download_file(service, file_id: str) -> bytes:
    """Download file bytes from Google Drive."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return fh.getvalue()


def _load_state() -> Dict:
    """Load poller state (last processed file IDs and timestamp)."""
    if POLLER_STATE_FILE.exists():
        with open(POLLER_STATE_FILE, "r") as f:
            return json.load(f)
    return {"processed_ids": [], "last_run": None}


def _save_state(state: Dict):
    """Save poller state to disk."""
    POLLER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(POLLER_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def list_files_in_folder(service, folder_id: str, page_size: int = 50) -> List[Dict]:
    """List files in a Drive folder."""
    q = f"'{folder_id}' in parents and trashed=false"
    res = service.files().list(
        q=q,
        pageSize=page_size,
        fields="files(id,name,modifiedTime,mimeType,size)",
        orderBy="createdTime desc"
    ).execute()
    return res.get("files", [])


def poll_drive_folder(folder_id: str, lang_mode: str = "eng"):
    """
    Poll a Google Drive folder for new files and enqueue ingestion.
    
    Args:
        folder_id: Google Drive folder ID to watch
        lang_mode: Language mode for OCR (eng, khm, eng+khm)
    """
    try:
        service = _build_service()
        state = _load_state()
        processed_ids = set(state.get("processed_ids", []))
        
        files = list_files_in_folder(service, folder_id)
        
        new_count = 0
        for file_info in files:
            file_id = file_info["id"]
            
            if file_id in processed_ids:
                print(f"  Skip (already processed): {file_info['name']}")
                continue
            
            # Check file type: skip unsupported types
            mime = file_info.get("mimeType", "")
            if mime.startswith("application/vnd.google-apps"):
                print(f"  Skip (Google Workspace doc): {file_info['name']}")
                continue
            
            print(f"  Downloading: {file_info['name']} ({file_info.get('size', '?')} bytes)")
            try:
                file_bytes = download_file(service, file_id)
                
                # Enqueue Celery task
                task = ingest_and_index_file.delay(
                    file_bytes,
                    file_info["name"],
                    "google_drive",
                    lang_mode=lang_mode
                )
                print(f"    ✓ Enqueued task {task.id} for {file_info['name']}")
                
                processed_ids.add(file_id)
                new_count += 1
            except Exception as e:
                print(f"    ✗ Error downloading {file_info['name']}: {e}")
        
        # Update state
        state["processed_ids"] = list(processed_ids)
        state["last_run"] = datetime.now().isoformat()
        _save_state(state)
        
        print(f"\nPoller complete: {new_count} new file(s) queued, "
              f"{len(processed_ids)} total processed.")
        
    except Exception as e:
        print(f"Poller error: {e}")
        raise


def run_poller_loop(folder_id: str, interval_sec: int = 60, lang_mode: str = "eng"):
    """
    Run poller in infinite loop (for systemd/cron, or development).
    
    Args:
        folder_id: Google Drive folder ID
        interval_sec: Polling interval in seconds (default 60)
        lang_mode: OCR language mode
    """
    print(f"Starting Drive poller for folder {folder_id}")
    print(f"Polling every {interval_sec} seconds...")
    
    while True:
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{ts}] Polling...")
            poll_drive_folder(folder_id, lang_mode=lang_mode)
        except Exception as e:
            print(f"[{ts}] Error in polling loop: {e}")
        
        time.sleep(interval_sec)


if __name__ == "__main__":
    # Example: set these from env or command line
    DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "your-folder-id-here")
    POLL_INTERVAL = int(os.getenv("DRIVE_POLL_INTERVAL_SEC", "60"))
    
    if DRIVE_FOLDER_ID == "your-folder-id-here":
        print("ERROR: Set DRIVE_FOLDER_ID env var to your target folder ID")
        print("Get it from: https://drive.google.com/drive/folders/FOLDER_ID")
        exit(1)
    
    run_poller_loop(DRIVE_FOLDER_ID, interval_sec=POLL_INTERVAL)