import sys
sys.path.insert(0, "src")
try:
    from document_processing.ocr import pytesseract_ocr
    print('import-ok')
except Exception as e:
    print('import-failed', e)
    raise
