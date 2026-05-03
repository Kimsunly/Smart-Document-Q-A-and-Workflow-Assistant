from document_processing.pdf_router import PDFRouter
import sys
sys.path.insert(0, 'src')

router = PDFRouter(text_threshold=100)
text, method, metadata = router.route_pdf(
    'data/pdfs/Midterm-doc.pdf', apply_ocr=True, lang_mode='eng+khm')
print('method:', method)
print('classification:', metadata.get('classification'))
print('mixed_pages:', metadata.get('mixed_pages'))
print('text_pages:', metadata.get('text_pages'))
print('zero_text_pages:', metadata.get('zero_text_pages'))
print('text_preview:', text[:500].replace('\n', ' | '))
