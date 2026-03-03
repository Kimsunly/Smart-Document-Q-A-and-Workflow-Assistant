import argparse
import os
import shutil
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import cv2
import numpy as np
import pytesseract

from common.logger import document_logger
from document_processing.ocr.preprocess import preprocess_pipeline
from text_processing.ocr_cleanup import clean_ocr_text


def _ensure_tesseract_path() -> None:
    if shutil.which("tesseract") is None:
        win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(win_path):
            pytesseract.pytesseract.tesseract_cmd = win_path


def run_tesseract(image: np.ndarray) -> Tuple[str, float]:
    _ensure_tesseract_path()
    config = r"--oem 3 --psm 6 -l eng -c preserve_interword_spaces=1"
    data = pytesseract.image_to_data(
        image,
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
    return cleaned_text, avg_conf


def compute_metrics(
    text: str,
    avg_conf: float,
    ground_truth: Optional[str]
) -> Dict[str, float]:
    words = [w for w in text.split() if w.strip()]
    alnum_count = sum(1 for c in text if c.isalnum())
    total_count = len(text)
    alnum_ratio = float(alnum_count / total_count) if total_count else 0.0

    metrics: Dict[str, float] = {
        "char_count": float(len(text)),
        "word_count": float(len(words)),
        "avg_conf": float(avg_conf),
        "alnum_ratio": float(alnum_ratio),
        "unique_word_ratio": float(len(set(words)) / len(words)) if words else 0.0,
    }

    if ground_truth is not None:
        ratio = SequenceMatcher(None, ground_truth, text).ratio()
        metrics["similarity"] = float(ratio)
        metrics["cer"] = float(1.0 - ratio)

    return metrics


def format_metrics(title: str, metrics: Dict[str, float]) -> str:
    lines = [f"{title}:"]
    for key, value in metrics.items():
        if key in {"similarity", "cer", "alnum_ratio", "unique_word_ratio"}:
            lines.append(f"  - {key}: {value:.4f}")
        else:
            lines.append(f"  - {key}: {value:.2f}")
    return "\n".join(lines)


def compare_metrics(
    before: Dict[str, float],
    after: Dict[str, float]
) -> Dict[str, float]:
    keys = set(before.keys()).intersection(after.keys())
    return {key: after[key] - before[key] for key in keys}


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR comparison: raw vs preprocessed")
    parser.add_argument(
        "--image",
        default=str(ROOT_DIR / "data" / "images_for_ocr_test" / "image.png"),
        help="Path to baseline image"
    )
    parser.add_argument(
        "--ground-truth",
        default=None,
        help="Optional path to ground-truth text file"
    )
    parser.add_argument(
        "--report",
        default=str(ROOT_DIR / "reports" / "daily-reports" / "day-3.txt"),
        help="Output report file path"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save preprocessing debug images"
    )

    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"Baseline image not found: {image_path}")

    ground_truth_text: Optional[str] = None
    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        if gt_path.exists():
            ground_truth_text = gt_path.read_text(encoding="utf-8")
        else:
            document_logger.warning(
                f"Ground-truth file not found: {gt_path} (skipping accuracy)"
            )

    document_logger.info(f"Running OCR comparison for: {image_path}")

    original = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if original is None:
        raise ValueError(f"Unsupported or corrupted image file: {image_path}")

    raw_text, raw_conf = run_tesseract(original)
    raw_metrics = compute_metrics(raw_text, raw_conf, ground_truth_text)

    debug_dir = str(ROOT_DIR / "debug" / "preprocess") if args.debug else None
    processed, timings = preprocess_pipeline(
        str(image_path),
        debug_dir=debug_dir,
        return_timings=True
    )

    processed_text, processed_conf = run_tesseract(processed)
    processed_metrics = compute_metrics(
        processed_text, processed_conf, ground_truth_text
    )

    deltas = compare_metrics(raw_metrics, processed_metrics)

    report_lines = [
        "Day 3 - OCR Preprocessing Comparison",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Image: {image_path}",
        "",
        format_metrics("Raw OCR Metrics", raw_metrics),
        "",
        format_metrics("Preprocessed OCR Metrics", processed_metrics),
        "",
        format_metrics("Delta (Preprocessed - Raw)", deltas),
        ""
    ]

    if timings:
        report_lines.append("Preprocessing Timings (ms):")
        for key, value in timings.items():
            report_lines.append(f"  - {key}: {value:.2f}")

    report_text = "\n".join(report_lines)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    document_logger.info("OCR comparison completed")
    document_logger.info(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()