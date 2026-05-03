from document_processing.pdf_router import PDFRouter
import sys
sys.path.insert(0, 'src')

router = PDFRouter(text_threshold=100)
path = r'data/pdfs/scanned_sample1.pdf'

try:
    cls, cnt, md = router.classify_pdf(path)
    print('classification:', cls)
    print('char_count:', cnt)
    print('zero_text_pages:', md.get('zero_text_pages'))
    print('page_char_counts:', md.get('page_char_counts'))
except Exception as e:
    print('error:', e)
