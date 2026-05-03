from text_processing.ocr_cleanup import clean_ocr_text
from document_processing.ocr.preprocess import preprocess_for_tesseract
from common.logger import document_logger
import pytesseract
import cv2
import argparse
import csv
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _ensure_tesseract_path() -> None:
    if shutil.which("tesseract") is None:
        win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(win_path):
            pytesseract.pytesseract.tesseract_cmd = win_path

    tessdata_dir = r"C:\Program Files\Tesseract-OCR\tessdata"
    if os.path.exists(tessdata_dir):
        os.environ.setdefault("TESSDATA_PREFIX", tessdata_dir)


def _levenshtein(a: List[str], b: List[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


def compute_cer(gt: str, pred: str) -> float:
    gt_chars = list(gt)
    pred_chars = list(pred)
    dist = _levenshtein(gt_chars, pred_chars)
    return float(dist / max(1, len(gt_chars)))


def compute_wer(gt: str, pred: str) -> float:
    gt_words = [w for w in gt.split() if w.strip()]
    pred_words = [w for w in pred.split() if w.strip()]
    dist = _levenshtein(gt_words, pred_words)
    return float(dist / max(1, len(gt_words)))


def run_tesseract(image, lang: str, psm: int) -> Tuple[str, float]:
    config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"
    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        config=config,
        lang=lang,
    )

    words = [w for w in data.get("text", []) if w and w.strip()]
    raw_text = " ".join(words)

    conf_values: List[float] = []
    for c in data.get("conf", []):
        try:
            c = float(c)
            if c >= 0:
                conf_values.append(c)
        except Exception:
            pass

    avg_conf = float(sum(conf_values) / len(conf_values)
                     ) if conf_values else 0.0
    return clean_ocr_text(raw_text), avg_conf


def khmer_ink_variant(image_path: str):
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        return None

    h, w = img.shape[:2]
    if min(h, w) < 900:
        img = cv2.resize(img, None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)

    b, g, r = cv2.split(img)
    rg = cv2.max(r, g)
    ink = cv2.subtract(b, rg)

    _, mask = cv2.threshold(ink, 18, 255, cv2.THRESH_BINARY)

    line_w = max(30, mask.shape[1] // 18)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (line_w, 1))
    h_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, h_kernel)
    mask = cv2.subtract(mask, h_lines)

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
    mask = cv2.medianBlur(mask, 3)

    return 255 - mask


def generate_variants(image_path: str, debug_dir: Optional[Path]) -> Dict[str, object]:
    src = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if src is None:
        raise ValueError(f"Cannot read image: {image_path}")

    strong = preprocess_for_tesseract(
        image_path, debug_dir=str(debug_dir) if debug_dir else None)
    ink = khmer_ink_variant(image_path)

    variants: Dict[str, object] = {
        "raw_psm6": src,
        "strong_psm6": strong,
        "strong_psm11": strong,
        "strong_psm12": strong,
    }

    if ink is not None:
        variants["ink_psm6"] = ink
        variants["ink_psm11"] = ink
        variants["ink_psm12"] = ink

    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_dir / "variant_raw.png"), src)
        cv2.imwrite(str(debug_dir / "variant_strong.png"), strong)
        if ink is not None:
            cv2.imwrite(str(debug_dir / "variant_ink.png"), ink)

    return variants


def psm_for_variant(name: str) -> int:
    if name.endswith("psm11"):
        return 11
    if name.endswith("psm12"):
        return 12
    return 6


def iter_images(images_dir: Path) -> List[Path]:
    exts = ("*.png", "*.jpg", "*.jpeg")
    files: List[Path] = []
    for ext in exts:
        files.extend(images_dir.glob(ext))
    return sorted(files)


def load_ground_truth(labels_dir: Path, image_path: Path) -> Optional[str]:
    label_path = labels_dir / f"{image_path.stem}.txt"
    if not label_path.exists():
        return None
    return label_path.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Khmer handwriting OCR variants with CER/WER leaderboard"
    )
    parser.add_argument(
        "--image",
        default="",
        help="Optional single image path to evaluate (overrides --images-dir)",
    )
    parser.add_argument(
        "--images-dir",
        default=str(ROOT_DIR / "data" / "images_for_ocr_test"),
        help="Directory containing test images (.png/.jpg/.jpeg)",
    )
    parser.add_argument(
        "--ground-truth-file",
        default="",
        help="Optional ground-truth text file for --image mode",
    )
    parser.add_argument(
        "--labels-dir",
        default=str(ROOT_DIR / "data" / "images_for_ocr_test" / "labels"),
        help="Directory containing ground-truth .txt files with same basename as images",
    )
    parser.add_argument(
        "--lang",
        default="khm",
        help="Tesseract language mode (default: khm)",
    )
    parser.add_argument(
        "--report-txt",
        default=str(ROOT_DIR / "reports" / "daily-reports" /
                    "khmer_ocr_leaderboard.txt"),
        help="Leaderboard report path",
    )
    parser.add_argument(
        "--report-csv",
        default=str(ROOT_DIR / "reports" / "daily-reports" /
                    "khmer_ocr_samples.csv"),
        help="Per-sample metrics csv path",
    )
    parser.add_argument(
        "--debug-dir",
        default=str(ROOT_DIR / "debug" / "khmer_eval"),
        help="Directory to write debug variant images",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max image count (0 = all)",
    )

    args = parser.parse_args()
    _ensure_tesseract_path()

    images_dir = Path(args.images_dir)
    labels_dir = Path(args.labels_dir)
    debug_root = Path(args.debug_dir)

    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        images = [image_path]
    else:
        if not images_dir.exists():
            raise FileNotFoundError(f"Images dir not found: {images_dir}")

        images = iter_images(images_dir)
        if args.limit > 0:
            images = images[: args.limit]

        if not images:
            raise FileNotFoundError(f"No images found in: {images_dir}")

    sample_rows: List[Dict[str, object]] = []
    grouped: Dict[str, Dict[str, List[float]]
                  ] = defaultdict(lambda: defaultdict(list))

    for image_path in images:
        if args.ground_truth_file and args.image:
            gt_path = Path(args.ground_truth_file)
            gt = gt_path.read_text(
                encoding="utf-8") if gt_path.exists() else None
        else:
            gt = load_ground_truth(labels_dir, image_path)
        debug_dir = debug_root / image_path.stem

        variants = generate_variants(str(image_path), debug_dir)
        for variant_name, variant_img in variants.items():
            psm = psm_for_variant(variant_name)
            text, conf = run_tesseract(variant_img, args.lang, psm)

            cer = compute_cer(gt, text) if gt is not None else None
            wer = compute_wer(gt, text) if gt is not None else None

            sample_rows.append(
                {
                    "image": image_path.name,
                    "variant": variant_name,
                    "confidence": round(conf, 4),
                    "cer": round(cer, 6) if cer is not None else "",
                    "wer": round(wer, 6) if wer is not None else "",
                    "text_preview": text[:120].replace("\n", " "),
                }
            )

            grouped[variant_name]["confidence"].append(conf)
            if cer is not None:
                grouped[variant_name]["cer"].append(cer)
            if wer is not None:
                grouped[variant_name]["wer"].append(wer)

    leaderboard = []
    for variant, vals in grouped.items():
        avg_conf = mean(vals["confidence"]) if vals["confidence"] else 0.0
        avg_cer = mean(vals["cer"]) if vals.get("cer") else None
        avg_wer = mean(vals["wer"]) if vals.get("wer") else None
        leaderboard.append(
            {
                "variant": variant,
                "avg_conf": avg_conf,
                "avg_cer": avg_cer,
                "avg_wer": avg_wer,
                "samples": len(vals["confidence"]),
            }
        )

    def rank_key(item):
        cer = item["avg_cer"] if item["avg_cer"] is not None else 999.0
        wer = item["avg_wer"] if item["avg_wer"] is not None else 999.0
        return (cer, wer, -item["avg_conf"])

    leaderboard.sort(key=rank_key)

    report_txt = Path(args.report_txt)
    report_txt.parent.mkdir(parents=True, exist_ok=True)
    report_csv = Path(args.report_csv)
    report_csv.parent.mkdir(parents=True, exist_ok=True)

    with report_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["image", "variant", "confidence",
                        "cer", "wer", "text_preview"],
        )
        writer.writeheader()
        writer.writerows(sample_rows)

    lines = [
        "Khmer Handwriting OCR Benchmark",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Images dir: {images_dir}",
        f"Labels dir: {labels_dir}",
        f"Lang: {args.lang}",
        f"Samples: {len(images)}",
        "",
        "Leaderboard (lower CER/WER is better):",
    ]

    for i, row in enumerate(leaderboard, start=1):
        cer_s = f"{row['avg_cer']:.4f}" if row["avg_cer"] is not None else "N/A"
        wer_s = f"{row['avg_wer']:.4f}" if row["avg_wer"] is not None else "N/A"
        lines.append(
            f"{i}. {row['variant']}: CER={cer_s}, WER={wer_s}, "
            f"Conf={row['avg_conf']:.2f}, Samples={row['samples']}"
        )

    lines.extend(
        [
            "",
            f"Per-sample CSV: {report_csv}",
            f"Debug variants: {debug_root}",
        ]
    )

    report_txt.write_text("\n".join(lines), encoding="utf-8")

    document_logger.info("Khmer OCR benchmark completed")
    document_logger.info(f"Leaderboard report: {report_txt}")
    document_logger.info(f"Per-sample CSV: {report_csv}")


if __name__ == "__main__":
    main()
