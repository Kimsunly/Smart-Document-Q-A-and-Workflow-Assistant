import os
from document_processing.ocr.pytesseract_ocr import extract_text_from_image
import sys
sys.path.insert(0, "src")
folder = 'data/images_for_ocr_test'
for f in os.listdir(folder):
    path = os.path.join(folder, f)
    print('---', f)
    try:
        cleaned, preview, raw, conf = extract_text_from_image(
            path, lang_mode='eng+khm', debug=False)
        print('CLEANED:', cleaned[:400])
        print('RAW   :', raw[:400])
        print('CONF  :', conf)
    except Exception as e:
        print('ERROR :', e)
