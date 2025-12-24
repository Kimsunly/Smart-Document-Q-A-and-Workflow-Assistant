# src/document_processing/ocr/paddle_ocr.py

import cv2
from typing import Tuple

try:
    from paddleocr import PaddleOCR
    _paddle_available = True
except Exception as e:
    _paddle_available = False
    print("PaddleOCR not usable:", e)

# Lazy initialization to avoid heavy startup if not used
_paddle_ocr = None


def _init_paddle():
    """
    Initialize PaddleOCR with English model and angle classifier.
    """
    global _paddle_ocr
    if _paddle_ocr is None:
        _paddle_ocr = PaddleOCR(lang='en', use_angle_cls=True)
    return _paddle_ocr


def extract_text_paddle(image_path: str, debug: bool = False):
    """
    Extract text from an image using PaddleOCR.

    Returns:
        cleaned_text: human-readable text after OCR
        preprocessed_image: binarized RGB image for preview
        raw_text_output: raw OCR text with confidence
        avg_conf: average OCR confidence in percentage
    """
    if not _paddle_available:
        raise ImportError(
            "PaddleOCR is not installed. Install with `pip install paddleocr`")

    ocr = _init_paddle()
    img = cv2.imread(image_path)
    if img is None:
        return "", None, "", 0.0

    # Preprocess image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.resize(gray, None, fx=1.6, fy=1.6,
                      interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # OCR call
    ocr_results = ocr.ocr(thresh)

    extracted_texts = []
    raw_pieces = []
    confs = []

    # Support both old (list/tuple) and new (dict) API formats
    for word_info in ocr_results:
        try:
            # Old API: [bbox, (text, confidence)]
            if isinstance(word_info, list) and len(word_info) == 2:
                text, conf = word_info[1]
            # New API: dict with 'text' and 'confidence'
            elif isinstance(word_info, dict):
                text = word_info.get('text', '')
                conf = word_info.get('confidence', 0.0)
            else:
                continue

            if not text.strip():
                continue

            extracted_texts.append(text)
            raw_pieces.append(f"{text} ({float(conf):.2f})")
            confs.append(float(conf) * 100)
        except Exception:
            continue

    raw_text_output = " ".join(raw_pieces)
    cleaned_text = " ".join(extracted_texts).strip()
    avg_conf = float(sum(confs) / len(confs)) if confs else 0.0

    preprocessed_image = cv2.cvtColor(
        thresh, cv2.COLOR_GRAY2RGB) if debug else None
    if debug:
        cv2.imwrite("debug_paddle_original.png", img)
        cv2.imwrite("debug_paddle_preprocessed.png", thresh)

    return cleaned_text, preprocessed_image, raw_text_output.strip(), avg_conf
