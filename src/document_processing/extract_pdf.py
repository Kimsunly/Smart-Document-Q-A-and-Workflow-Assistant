
from pypdf import PdfReader

def extract_text_from_pdf(file_like):
    """
    Extract text from PDF using its text layer (no OCR).
    `file_like` can be a path or a BytesIO.
    """
    text = ""
    reader = PdfReader(file_like)
    for page in reader.pages:
        page_text = page.extract_text() or ""
        text += page_text
    return text
