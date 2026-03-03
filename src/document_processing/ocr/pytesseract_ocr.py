# src/document_processing/ocr/pytesseract_ocr.py
import os
import shutil
from typing import Optional, Tuple

import pytesseract
from document_processing.ocr.preprocess import preprocess_for_tesseract
from text_processing.ocr_cleanup import clean_ocr_text


# Use PATH 'tesseract' if available; otherwise try Windows default
if shutil.which("tesseract") is None:
    win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(win_path):
        pytesseract.pytesseract.tesseract_cmd = win_path


def extract_text_from_image(image_path: str, debug: bool = False) -> Tuple[str, Optional[object], str, float]:
    """
    Returns: cleaned_text, preprocessed_image(None), raw_text_output, avg_conf(0..100)
    """
    debug_dir = "debug/tesseract" if debug else None
    preproc = preprocess_for_tesseract(image_path, debug_dir=debug_dir)

    config = r"--oem 3 --psm 6 -l eng -c preserve_interword_spaces=1"

    data = pytesseract.image_to_data(
        preproc,
        output_type=pytesseract.Output.DICT,
        config=config
    )

    words = [w for w in data.get("text", []) if w and w.strip()]
    raw_text_output = " ".join(words)

    conf_values = []
    for c in data.get("conf", []):
        try:
            c = float(c)
            if c >= 0:
                conf_values.append(c)
        except Exception:
            pass

    avg_conf = float(sum(conf_values) / len(conf_values)) if conf_values else 0.0
    cleaned_text = clean_ocr_text(raw_text_output)

    return cleaned_text, None, raw_text_output, avg_conf
