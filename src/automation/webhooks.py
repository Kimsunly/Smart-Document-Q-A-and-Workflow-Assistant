from fastapi import FastAPI, Request, UploadFile, File, BackgroundTasks
from automation.tasks import ingest_and_index_file

app = FastAPI(title="Automation webhooks")

@app.post("/webhook/drive")
async def drive_webhook(payload: dict, background_tasks: BackgroundTasks):
    # payload should contain an identifier you use to download the file.
    file_id = payload.get("file_id")
    name = payload.get("name", "drive_file")
    # TODO: implement download_drive_file(file_id) in google_drive.py
    from automation.google_drive import download_drive_file
    file_bytes = download_drive_file(file_id)
    background_tasks.add_task(ingest_and_index_file.delay, file_bytes, name, "google_drive")
    return {"ok": True}

@app.post("/webhook/dropbox")
async def dropbox_webhook(payload: dict, background_tasks: BackgroundTasks):
    # payload usually contains path or id; implement download in dropbox.py
    path = payload.get("path_lower")
    from automation.dropbox import download_dropbox_file
    file_bytes, name = download_dropbox_file(path)
    background_tasks.add_task(ingest_and_index_file.delay, file_bytes, name, "dropbox")
    return {"ok": True}

@app.post("/upload-file")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    content = await file.read()
    background_tasks.add_task(ingest_and_index_file.delay, content, file.filename, "http_upload")
    return {"status": "enqueued", "filename": file.filename}