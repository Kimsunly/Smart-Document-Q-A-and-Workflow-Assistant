# minimal Drive helper (poller + download)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import io
from googleapiclient.http import MediaIoBaseDownload
from automation.config import GOOGLE_CREDENTIALS_JSON

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

def _build_service():
    creds = None
    if GOOGLE_CREDENTIALS_JSON:
        creds = service_account.Credentials.from_service_account_file(GOOGLE_CREDENTIALS_JSON, scopes=SCOPES)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return service

def download_drive_file(file_id: str) -> bytes:
    svc = _build_service()
    request = svc.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return fh.getvalue()

def list_files_in_folder(folder_id: str, page_size: int = 50):
    svc = _build_service()
    q = f"'{folder_id}' in parents and trashed=false"
    res = svc.files().list(q=q, pageSize=page_size, fields="files(id,name,modifiedTime)").execute()
    return res.get("files", [])