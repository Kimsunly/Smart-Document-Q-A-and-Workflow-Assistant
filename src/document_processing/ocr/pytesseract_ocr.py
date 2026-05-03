# src/document_processing/ocr/pytesseract_ocr.py
import os
import shutil
from typing import Optional, Tuple

import pytesseract
import cv2
from common.logger import document_logger
from document_processing.ocr.preprocess import preprocess_for_tesseract
from text_processing.ocr_cleanup import clean_ocr_text


# Use PATH 'tesseract' if available; otherwise try Windows default
if shutil.which("tesseract") is None:
    win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(win_path):
        pytesseract.pytesseract.tesseract_cmd = win_path

# Ensure tessdata directory is discoverable on Windows installs.
win_tessdata_dir = r"C:\Program Files\Tesseract-OCR\tessdata"
if os.path.exists(win_tessdata_dir):
    os.environ.setdefault("TESSDATA_PREFIX", win_tessdata_dir)


def extract_text_from_image(image_path: str, lang_mode: str = "eng", debug: bool = False, ink_threshold: int = 18) -> Tuple[str, Optional[object], str, float]:
    """
    Returns: cleaned_text, preprocessed_image(None), raw_text_output, avg_conf(0..100)
    """
    debug_dir = "debug/tesseract" if debug else None
    preproc = preprocess_for_tesseract(image_path, debug_dir=debug_dir)

    def khmer_ink_variant(path: str, threshold: int = 18):
        """
        Build a Khmer-friendly binary image from blue-ink handwriting on ruled paper.
        Returns black-text-on-white image for Tesseract.
        """
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            return None

        h, w = img.shape[:2]
        if min(h, w) < 900:
            img = cv2.resize(img, None, fx=2.0, fy=2.0,
                             interpolation=cv2.INTER_CUBIC)

        b, g, r = cv2.split(img)
        rg = cv2.max(r, g)
        ink = cv2.subtract(b, rg)

        # Keep strong blue strokes only.
        _, mask = cv2.threshold(ink, threshold, 255, cv2.THRESH_BINARY)

        # Remove long horizontal ruled lines if present.
        line_w = max(30, mask.shape[1] // 18)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (line_w, 1))
        h_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, h_kernel)
        mask = cv2.subtract(mask, h_lines)

        # Connect broken pen strokes and reduce speckles.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
        mask = cv2.medianBlur(mask, 3)

        # Tesseract expects dark text on light background.
        return 255 - mask

    def resolve_lang(mode):
        if mode == "khm":
            return "khm"
        if mode in ("eng+khm", "khm+eng", "mixed"):
            return "eng+khm"
        return "eng"

    def resolve_available_lang(requested_lang: str) -> str:
        """Fallback to available Tesseract langs if requested packs are missing."""
        try:
            available = set(pytesseract.get_languages(config=""))
        except Exception:
            available = {"eng"}

        requested_parts = [p for p in requested_lang.split("+") if p]
        valid_parts = [p for p in requested_parts if p in available]

        if valid_parts:
            selected = "+".join(valid_parts)
            if selected != requested_lang:
                document_logger.warning(
                    f"Requested OCR language '{requested_lang}' not fully available; "
                    f"falling back to '{selected}'. Available: {sorted(available)}"
                )
            return selected

        if "eng" in available:
            document_logger.warning(
                f"Requested OCR language '{requested_lang}' unavailable; "
                f"falling back to 'eng'. Available: {sorted(available)}"
            )
            return "eng"

        # Last-resort fallback for unusual setups.
        selected = sorted(available)[0] if available else "eng"
        document_logger.warning(
            f"No requested OCR language available; using '{selected}'."
        )
        return selected

    lang = resolve_available_lang(resolve_lang(lang_mode))

    def run_with_psm(image, psm: int, oem: int = 1):
        config = f"--oem {oem} --psm {psm} -c preserve_interword_spaces=1"
        return pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            config=config,
            lang=lang
        )

    def avg_conf(data_dict):
        vals = []
        for c in data_dict.get("conf", []):
            try:
                c = float(c)
                if c >= 0:
                    vals.append(c)
            except Exception:
                pass
        return float(sum(vals) / len(vals)) if vals else 0.0

    def extract_text(data_dict):
        # Reconstruct lines from Tesseract output using block/par/line grouping
        texts = data_dict.get("text", [])
        blocks = data_dict.get("block_num", [])
        pars = data_dict.get("par_num", [])
        lines_idx = data_dict.get("line_num", [])

        grouped = {}
        for i, word in enumerate(texts):
            if not word or not word.strip():
                continue
            key = (blocks[i] if i < len(blocks) else 0,
                   pars[i] if i < len(pars) else 0,
                   lines_idx[i] if i < len(lines_idx) else 0)
            grouped.setdefault(key, []).append(word)

        # Sort keys for deterministic line order
        out_lines = []
        for key in sorted(grouped.keys()):
            out_lines.append(" ".join(grouped[key]).strip())

        return "\n".join(out_lines)

    def text_len(data_dict):
        return len(extract_text(data_dict))

    def khmer_ratio(text: str) -> float:
        if not text:
            return 0.0
        kh_chars = sum(1 for ch in text if "\u1780" <= ch <= "\u17ff")
        return float(kh_chars / max(len(text), 1))

    def noise_ratio(text: str) -> float:
        if not text:
            return 1.0
        noisy = sum(1 for ch in text if ch in "|_-=+*~`^{}[]<>\\/")
        return float(noisy / max(len(text), 1))

    def score_candidate(data_dict):
        txt = extract_text(data_dict)
        base = avg_conf(data_dict) + min(len(txt), 300) * 0.06

        # Language-specific boosts: prefer Khmer glyphs for khm-heavy docs,
        # and prefer mixed outputs when user requested mixed mode.
        eng_chars = sum(1 for ch in txt if (
            'A' <= ch <= 'Z') or ('a' <= ch <= 'z'))
        eng_ratio = float(eng_chars / max(len(txt), 1))
        k_ratio = khmer_ratio(txt)
        n_ratio = noise_ratio(txt)

        # If user explicitly requested mixed, reward presence of both scripts.
        if lang_mode in ("eng+khm", "mixed", "khm+eng"):
            base += k_ratio * 160.0
            base += eng_ratio * 60.0
            base -= n_ratio * 120.0
        elif "khm" in lang:
            base += k_ratio * 220.0
            base -= n_ratio * 120.0
        else:
            # English preference
            base += eng_ratio * 80.0
            base -= n_ratio * 80.0

        return base

    # Khmer or mixed mode: generate a wider set of candidate images and OCR configs
    # to handle bilingual pages (Khmer + English) and blue-ink variants.
    if "khm" in lang or lang_mode in ("eng+khm", "mixed"):
        if len(preproc.shape) == 3:
            gray = cv2.cvtColor(preproc, cv2.COLOR_BGR2GRAY)
        else:
            gray = preproc

        # Upscale and create several binarization variants
        up = cv2.resize(gray, None, fx=2.0, fy=2.0,
                        interpolation=cv2.INTER_CUBIC)
        up_blur = cv2.GaussianBlur(up, (3, 3), 0)
        otsu = cv2.threshold(
            up_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        adapt = cv2.adaptiveThreshold(
            up_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12
        )
        adapt_tight = cv2.adaptiveThreshold(
            up_blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 21, 8
        )

        # Inverted / cleaned variants
        inv = 255 - otsu
        morph = cv2.morphologyEx(
            otsu, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))

        candidates = [up, otsu, adapt, adapt_tight, inv, morph]

        ink_variant = khmer_ink_variant(image_path, threshold=ink_threshold)
        if ink_variant is not None:
            candidates.append(ink_variant)

        trials = []
        # Try a larger config grid: multiple PSMs and OEMs to find best fit.
        psm_list = [3, 6, 11, 12]
        oem_list = [1, 3]
        for cand in candidates:
            for p in psm_list:
                for o in oem_list:
                    try:
                        trials.append(run_with_psm(cand, p, o))
                    except Exception:
                        # ignore failing OCR attempts and continue
                        continue

        if trials:
            data = max(trials, key=score_candidate)
        else:
            # Fallback to single run
            data = run_with_psm(preproc, 6)
    else:
        data = run_with_psm(preproc, 6)

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

    avg_conf = float(sum(conf_values) / len(conf_values)
                     ) if conf_values else 0.0
    cleaned_text = clean_ocr_text(raw_text_output)

    return cleaned_text, None, raw_text_output, avg_conf
