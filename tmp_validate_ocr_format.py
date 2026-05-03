from document_processing.pdf_router import PDFRouter
import sys
import py_compile
from pathlib import Path

sys.path.insert(0, 'src')

files = [
    'src/document_processing/pdf_router.py',
    'src/app.py',
    'src/text_processing/document_format.py',
]

for file_path in files:
    try:
        py_compile.compile(file_path, doraise=True)
        print('OK', file_path)
    except Exception as e:
        print('ERR', file_path, type(e).__name__, e)

router = PDFRouter(text_threshold=100)
for pdf_path in ['data/pdfs/Midterm-doc.pdf', 'data/pdfs/digital_sample1.pdf', 'data/pdfs/scanned_sample1.pdf']:
    try:
        classification, char_count, metadata = router.classify_pdf(pdf_path)
        print(pdf_path, classification, char_count, metadata.get(
            'text_quality_score'), metadata.get('zero_text_pages'))
    except Exception as e:
        print('CLASSIFY_ERR', pdf_path, repr(e))
