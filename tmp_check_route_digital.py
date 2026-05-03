from document_processing.pdf_router import PDFRouter
import sys
sys.path.insert(0, 'src')

router = PDFRouter(text_threshold=100)
path = r'data/pdfs/digital_sample1.pdf'

cls, cnt, md = router.classify_pdf(path)
print('classification:', cls)
print('char_count:', cnt)
print('zero_text_pages:', md.get('zero_text_pages'))
print('page_char_counts(first3):', (md.get('page_char_counts') or [])[:3])
