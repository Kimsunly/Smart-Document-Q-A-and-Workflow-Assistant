import dropbox
from automation.config import DROPBOX_TOKEN

dbx = dropbox.Dropbox(DROPBOX_TOKEN)

def download_dropbox_file(path_lower: str):
    """Return (bytes, filename)"""
    md, res = dbx.files_download(path_lower)
    return res.content, md.name

def list_folder(path: str = ""):
    res = dbx.files_list_folder(path)
    return res.entries