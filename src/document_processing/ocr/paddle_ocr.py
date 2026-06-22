# src/document_processing/ocr/paddle_ocr.py
import cv2
import numpy as np
import re
from typing import Optional, Tuple, List, Any

try:
    from paddleocr import PaddleOCR
    _paddle_available = True
except Exception as e:
    _paddle_available = False
    print("PaddleOCR not usable:", e)

from document_processing.ocr.preprocess import preprocess_for_paddle

_paddle_ocr = None


def set_paddle_ocr_instance(inst):
    global _paddle_ocr
    _paddle_ocr = inst


def _init_paddle(lang: str = "en"):
    """
    PaddleOCR 3.x has interface changes; initialize safely.
    """
    global _paddle_ocr
    if _paddle_ocr is not None:
        return _paddle_ocr

    if not _paddle_available:
        raise ImportError("PaddleOCR not installed.")

    # Try parameters in order of newest -> oldest compatibility.
    # Different PaddleOCR versions reject unknown kwargs with ValueError.
    init_variants = [
        {"lang": lang, "use_textline_orientation": True},
        {"lang": lang, "use_angle_cls": True},
        {"lang": lang},
    ]

    last_error = None
    for kwargs in init_variants:
        try:
            _paddle_ocr = PaddleOCR(**kwargs)
            return _paddle_ocr
        except (TypeError, ValueError) as e:
            last_error = e

    raise RuntimeError(
        f"Unable to initialize PaddleOCR with supported argument sets. Last error: {last_error}"
    )

    return _paddle_ocr


def _group_reading_order(items: List[Tuple[Any, str, float]], y_thresh: float = 14.0):
    if not items:
        return []

    enriched = []
    for bbox, text, conf in items:
        pts = np.array(bbox, dtype=np.float32)
        x_min = float(np.min(pts[:, 0]))
        y_min = float(np.min(pts[:, 1]))
        enriched.append((y_min, x_min, bbox, text, conf))

    enriched.sort(key=lambda t: (t[0], t[1]))

    lines, cur = [], [enriched[0]]
    for item in enriched[1:]:
        if abs(item[0] - cur[-1][0]) <= y_thresh:
            cur.append(item)
        else:
            lines.append(cur)
            cur = [item]
    lines.append(cur)

    ordered = []
    for line in lines:
        line.sort(key=lambda t: t[1])
        ordered.extend(line)

    return [(bbox, text, conf) for (_, _, bbox, text, conf) in ordered]


def _group_lines(items: List[Tuple[Any, str, float]], y_thresh: float = 14.0):
    if not items:
        return []

    enriched = []
    for bbox, text, conf in items:
        pts = np.array(bbox, dtype=np.float32)
        x_min = float(np.min(pts[:, 0]))
        y_min = float(np.min(pts[:, 1]))
        enriched.append((y_min, x_min, bbox, text, conf))

    enriched.sort(key=lambda t: (t[0], t[1]))

    lines, cur = [], [enriched[0]]
    for item in enriched[1:]:
        if abs(item[0] - cur[-1][0]) <= y_thresh:
            cur.append(item)
        else:
            lines.append(cur)
            cur = [item]
    lines.append(cur)

    normalized = []
    for line in lines:
        line.sort(key=lambda t: t[1])
        normalized.append([(bbox, text, conf)
                          for (_, _, bbox, text, conf) in line])
    return normalized


def _format_items_with_lines(items: List[Tuple[Any, str, float]]) -> Tuple[str, str]:
    lines = _group_lines(items)
    if not lines:
        return "", ""

    clean_lines = []
    raw_lines = []
    for line in lines:
        # line is a list of (bbox, text, conf)
        # Sort line by x_min just in case
        line_enriched = []
        for bbox, text, conf in line:
            if not text:
                continue
            pts = np.array(bbox, dtype=np.float32)
            x_min = float(np.min(pts[:, 0]))
            x_max = float(np.max(pts[:, 0]))
            y_min = float(np.min(pts[:, 1]))
            y_max = float(np.max(pts[:, 1]))
            height = max(y_max - y_min, 1.0)
            line_enriched.append((x_min, x_max, height, text, conf))
            
        line_enriched.sort(key=lambda t: t[0])
        
        clean_tokens = []
        raw_tokens = []
        prev_x_max = None
        
        for x_min, x_max, height, text, conf in line_enriched:
            char_width = max(0.5 * height, 1.0)
            
            if prev_x_max is not None:
                gap = x_min - prev_x_max
                if gap > 0:
                    gap_in_spaces = gap / char_width
                    if gap_in_spaces >= 1.5:
                        spaces = " " * max(2, int(round(gap_in_spaces)))
                    else:
                        spaces = " "
                else:
                    spaces = ""
            else:
                spaces = ""
                
            clean_tokens.append(spaces + text)
            raw_tokens.append(f"{text} ({conf:.1f}%)")
            prev_x_max = x_max
            
        if clean_tokens:
            clean_lines.append("".join(clean_tokens))
        if raw_tokens:
            raw_lines.append(" | ".join(raw_tokens))

    cleaned_text = "\n".join(clean_lines).strip()
    raw_text = "\n".join(raw_lines).strip()
    return cleaned_text, raw_text



def _apply_handwriting_fixes(text: str) -> str:
    if not text:
        return text

    fixed_lines = []
    for line in text.splitlines():
        current = line.strip()
        if re.match(r"^his\s+is\b", current, flags=re.IGNORECASE):
            current = "T" + current
        fixed_lines.append(current)

    return "\n".join(fixed_lines).strip()


def _parse_paddle_any(results) -> Tuple[str, str, float, dict]:
    """
    Supports BOTH:
    - PaddleOCR 2.x style list: [ [ [bbox,(text,conf)], ... ] ]
    - PaddleOCR 3.x style result objects / iterator where each item has `.res`
      with keys like 'rec_texts', 'rec_scores', 'dt_polys', etc. [1](https://github.com/PaddlePaddle/PaddleOCR/discussions/14510)
    Returns: cleaned_text, raw_text, avg_conf, debug_info
    """
    debug_info = {"format": None, "num_pages": 0}

    # If it's an iterator/generator, materialize it
    try:
        if not isinstance(results, list):
            results = list(results)
    except Exception:
        pass

    # Case A: PaddleOCR 3.x result objects (have .res dict)
    if isinstance(results, list) and results and hasattr(results[0], "res"):
        debug_info["format"] = "paddle_v3_result_objects"
        debug_info["num_pages"] = len(results)

        items = []
        all_confs = []

        for r in results:
            res = getattr(r, "res", {}) or {}
            rec_texts = res.get("rec_texts", []) or []
            rec_scores = res.get("rec_scores", []) or []
            rec_polys = res.get("rec_polys", []) or res.get(
                "dt_polys", []) or []

            # rec_scores may be numpy array
            try:
                rec_scores = list(rec_scores)
            except Exception:
                rec_scores = []

            try:
                rec_polys = list(rec_polys)
            except Exception:
                rec_polys = []

            for idx, t in enumerate(rec_texts):
                if t and str(t).strip():
                    text = str(t).strip()
                    conf_val = 0.0
                    if idx < len(rec_scores):
                        try:
                            score = float(rec_scores[idx])
                            conf_val = score * \
                                100.0 if score <= 1.0 else min(score, 100.0)
                        except Exception:
                            conf_val = 0.0

                    if idx < len(rec_polys):
                        bbox = rec_polys[idx]
                    else:
                        bbox = np.array([
                            [float(idx), 0.0],
                            [float(idx + 1), 0.0],
                            [float(idx + 1), 1.0],
                            [float(idx), 1.0],
                        ], dtype=np.float32)

                    items.append((bbox, text, conf_val))
                    all_confs.append(conf_val)

            for s in rec_scores:
                try:
                    s = float(s)
                    # 0..1 in many cases, convert to percent
                    all_confs.append(s * 100.0 if s <= 1.0 else min(s, 100.0))
                except Exception:
                    pass

        cleaned, raw = _format_items_with_lines(items)
        cleaned = _apply_handwriting_fixes(cleaned)
        avg_conf = float(sum(all_confs) / len(all_confs)) if all_confs else 0.0
        return cleaned, raw, avg_conf, debug_info

    # Case B: PaddleOCR 3.x dict-like OCRResult where rec_texts/rec_scores are top-level keys
    if isinstance(results, list) and results:
        first = results[0]
        is_mapping_like = hasattr(first, "keys") and hasattr(first, "get")
        if is_mapping_like and ("rec_texts" in first or "rec_scores" in first):
            debug_info["format"] = "paddle_v3_mapping_result"
            debug_info["num_pages"] = len(results)

            items = []
            all_confs = []

            for r in results:
                rec_texts = r.get("rec_texts", []) or []
                rec_scores = r.get("rec_scores", []) or []
                rec_polys = r.get("rec_polys", []) or r.get(
                    "dt_polys", []) or []

                try:
                    rec_scores = list(rec_scores)
                except Exception:
                    rec_scores = []

                try:
                    rec_polys = list(rec_polys)
                except Exception:
                    rec_polys = []

                for idx, t in enumerate(rec_texts):
                    if t and str(t).strip():
                        text = str(t).strip()
                        conf_val = 0.0
                        if idx < len(rec_scores):
                            try:
                                score = float(rec_scores[idx])
                                conf_val = score * \
                                    100.0 if score <= 1.0 else min(
                                        score, 100.0)
                            except Exception:
                                conf_val = 0.0

                        if idx < len(rec_polys):
                            bbox = rec_polys[idx]
                        else:
                            bbox = np.array([
                                [float(idx), 0.0],
                                [float(idx + 1), 0.0],
                                [float(idx + 1), 1.0],
                                [float(idx), 1.0],
                            ], dtype=np.float32)

                        items.append((bbox, text, conf_val))
                        all_confs.append(conf_val)

                for s in rec_scores:
                    try:
                        s = float(s)
                        all_confs.append(s * 100.0 if s <=
                                         1.0 else min(s, 100.0))
                    except Exception:
                        pass

            cleaned, raw = _format_items_with_lines(items)
            cleaned = _apply_handwriting_fixes(cleaned)
            avg_conf = float(sum(all_confs) / len(all_confs)
                             ) if all_confs else 0.0
            return cleaned, raw, avg_conf, debug_info

    # Case C: PaddleOCR 2.x list format
    debug_info["format"] = "paddle_v2_list_format"
    items = []
    confs = []

    if results and isinstance(results, list):
        for page in results:
            if not page:
                continue
            debug_info["num_pages"] += 1
            for line in page:
                try:
                    if not (isinstance(line, (list, tuple)) and len(line) >= 2):
                        continue

                    bbox = line[0]
                    text_conf = line[1]

                    if not (isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2):
                        continue

                    text = str(text_conf[0]).strip()
                    conf = float(text_conf[1])
                    if not text:
                        continue

                    conf_pct = conf * \
                        100.0 if conf <= 1.0 else min(conf, 100.0)
                    items.append((bbox, text, conf_pct))
                    confs.append(conf_pct)
                except Exception:
                    continue

    items = _group_reading_order(items)
    cleaned_text, raw_text = _format_items_with_lines(items)
    cleaned_text = _apply_handwriting_fixes(cleaned_text)
    avg_conf = float(sum(confs) / len(confs)) if confs else 0.0

    return cleaned_text, raw_text, avg_conf, debug_info


def extract_text_paddle(
    image_path: str,
    debug: bool = False,
    lang: str = "en"
) -> Tuple[str, Optional[np.ndarray], str, float]:
    """
    Returns:
      cleaned_text, preprocessed_preview(RGB if debug), raw_text_output, avg_conf(0..100)
    """
    if not _paddle_available:
        raise ImportError("PaddleOCR not installed.")

    ocr = _init_paddle(lang=lang)

    # Light preprocessing for Paddle (keep natural image)
    debug_dir = "debug/paddle" if debug else None
    bgr = preprocess_for_paddle(image_path, debug_dir=debug_dir)

    # PaddleOCR generally performs best with RGB input [2](blob:https://www.microsoft365.com/1cdbee0f-8134-4d65-b09f-8513845fdb8a)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    # Try using numpy RGB first
    try:
        results = ocr.ocr(rgb, cls=True)
    except TypeError:
        results = ocr.ocr(rgb)

    cleaned_text, raw_text, avg_conf, _dbg = _parse_paddle_any(results)

    # If still empty, try passing path (some builds behave better with path I/O)
    if not cleaned_text.strip():
        try:
            results2 = ocr.ocr(image_path, cls=True)
        except TypeError:
            results2 = ocr.ocr(image_path)

        cleaned_text2, raw_text2, avg_conf2, _dbg2 = _parse_paddle_any(
            results2)
        # choose better
        if len(cleaned_text2) > len(cleaned_text):
            cleaned_text, raw_text, avg_conf = cleaned_text2, raw_text2, avg_conf2

    preprocessed_preview = rgb if debug else None
    return cleaned_text, preprocessed_preview, raw_text, avg_conf
