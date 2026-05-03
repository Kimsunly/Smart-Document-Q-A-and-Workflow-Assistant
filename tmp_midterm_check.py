from document_processing.pdf_router import PDFRouter
import sys
sys.path.insert(0, 'src')

r = PDFRouter(text_threshold=100)
try:
    cls, cnt, md = r.classify_pdf('data/pdfs/Midterm-doc.pdf')
    print('classification:', cls)
    print('char_count:', cnt)
    print('zero_text_pages:', md.get('zero_text_pages'))
    print('page_char_counts (first 10):',
          (md.get('page_char_counts') or [])[:10])
except Exception as e:
    print('classification-error:', repr(e))
