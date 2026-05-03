import os
from document_processing.ocr.pytesseract_ocr import extract_text_from_image
import sys
sys.path.insert(0, "src")
img = 'data/images_for_ocr_test/kh_image_test.png'
thresholds = [8, 12, 18, 28, 40]
for t in thresholds:
    try:
        cleaned, preview, raw, conf = extract_text_from_image(
            img, lang_mode='eng+khm', debug=False, ink_threshold=t)
        print(f'TH={t:2d} | CONF={conf:.2f} | CLEANED={cleaned[:80]}')
    except Exception as e:
        print('TH=', t, 'ERROR', e)
