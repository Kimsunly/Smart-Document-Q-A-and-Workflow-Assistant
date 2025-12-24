# src/document_processing/ocr/pytesseract_ocr.py

import cv2
import pytesseract
from text_processing.ocr_cleanup import clean_ocr_text

# Update this path if Tesseract is installed elsewhere
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def extract_text_from_image(image_path: str, debug: bool = False):
    """
    Tesseract-based OCR.
    Returns:
        cleaned_text: minimal normalized text (Option C)
        preprocessed_image: RGB image suitable for Streamlit preview or None
        raw_text_output: raw OCR words (joined) as Tesseract returned (no filtering)
        avg_conf: average confidence (0..100)
    """
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    # Preprocess: grayscale -> blur -> Otsu threshold
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(
        blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Optional small opening to remove specks but keep letters
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
    preproc = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    # For Streamlit preview (RGB)
    preprocessed_image = cv2.cvtColor(
        preproc, cv2.COLOR_GRAY2RGB) if debug else None
    if debug:
        cv2.imwrite("debug_tesseract_original.png", img)
        cv2.imwrite("debug_tesseract_preprocessed.png", preproc)

    # OCR: get data (we keep all words for raw preview)
    data = pytesseract.image_to_data(
        preproc, output_type=pytesseract.Output.DICT, config="--oem 3 --psm 1")

    # raw words (keep every detected word as-is)
    words = [w for w in data.get("text", []) if w and w.strip()]
    raw_text_output = " ".join(words)

    # compute avg confidence safely
    conf_values = []
    for c in data.get("conf", []):
        try:
            conf_values.append(float(c))
        except Exception:
            continue
    # filter out negative/confidence -1 which Tesseract sometimes returns for non-text
    conf_values = [c for c in conf_values if c >= 0]
    avg_conf = float(sum(conf_values) / len(conf_values)
                     ) if conf_values else 0.0

    # minimal cleaning (Option C)
    cleaned_text = clean_ocr_text(raw_text_output)

    return cleaned_text, preprocessed_image, raw_text_output, avg_conf
