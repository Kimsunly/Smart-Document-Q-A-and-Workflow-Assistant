# src/document_processing/ocr/preprocess.py
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from common.logger import document_logger


def _safe_write(debug_dir: Optional[str], name: str, img):
    if debug_dir:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(Path(debug_dir) / name), img)


def _log_step_time(step_name: str, elapsed_ms: float) -> None:
    document_logger.debug(
        f"Preprocess step '{step_name}' completed in {elapsed_ms:.2f} ms"
    )


def _timed_step(step_name: str, func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    _log_step_time(step_name, elapsed_ms)
    return result, elapsed_ms


def preprocess_pipeline(
    image_path: str,
    debug_dir: Optional[str] = None,
    return_timings: bool = False
) -> Tuple[np.ndarray, Optional[Dict[str, float]]]:
    """
    General preprocessing pipeline for OCR:
    1) Grayscale conversion
    2) Contrast normalization (CLAHE)
    3) Adaptive thresholding
    4) Noise reduction filtering

    Returns: processed image, timings (optional)
    """
    try:
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img is None:
            document_logger.error(
                f"Image read failed (unsupported or corrupted): {image_path}"
            )
            raise ValueError(
                f"Unsupported or corrupted image file: {image_path}"
            )

        timings: Dict[str, float] = {}

        gray, t = _timed_step("grayscale", cv2.cvtColor,
                              img, cv2.COLOR_BGR2GRAY)
        timings["grayscale_ms"] = t

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        norm, t = _timed_step("contrast_normalization", clahe.apply, gray)
        timings["contrast_normalization_ms"] = t

        thresh, t = _timed_step(
            "adaptive_threshold",
            cv2.adaptiveThreshold,
            norm,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            8,
        )
        timings["adaptive_threshold_ms"] = t

        denoised, t = _timed_step("noise_reduction", cv2.medianBlur, thresh, 3)
        timings["noise_reduction_ms"] = t

        _safe_write(debug_dir, "pre_01_gray.png", gray)
        _safe_write(debug_dir, "pre_02_contrast.png", norm)
        _safe_write(debug_dir, "pre_03_threshold.png", thresh)
        _safe_write(debug_dir, "pre_04_denoised.png", denoised)

        return denoised, timings if return_timings else None

    except cv2.error as error:
        document_logger.error(
            f"OpenCV error during preprocessing: {error}", exc_info=True
        )
        raise
    except Exception as error:
        document_logger.error(
            f"Unexpected preprocessing error: {error}", exc_info=True
        )
        raise


# -----------------------------
# Paddle preprocessing (LIGHT)
# -----------------------------
def preprocess_for_paddle(image_path: str, debug_dir: Optional[str] = None) -> np.ndarray:
    """
    Light preprocessing for PaddleOCR:
    - keep natural image (NO binarization)
    - upscale if small
    - gentle contrast enhancement (LAB + CLAHE)
    Returns: BGR image
    """
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"❌ Could not read image: {image_path}")

    h, w = img.shape[:2]
    if min(h, w) < 600:
        img = cv2.resize(img, None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l2 = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)

    _safe_write(debug_dir, "paddle_enhanced.png", enhanced)
    return enhanced


# -----------------------------
# Tesseract preprocessing (STRONG)
# -----------------------------
def _compute_skew_angle_from_binary(binary_inv: np.ndarray) -> float:
    """
    binary_inv: text=255, bg=0
    returns small angle in degrees
    """
    pts = cv2.findNonZero(binary_inv)
    if pts is None:
        return 0.0

    rect = cv2.minAreaRect(pts)
    angle = rect[-1]  # [-90, 0)
    if angle < -45:
        angle = 90 + angle
    return angle


def _rotate_gray(gray: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.05:
        return gray
    h, w = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255
    )


def preprocess_for_tesseract(image_path: str, debug_dir: Optional[str] = None) -> np.ndarray:
    """
    Strong preprocessing for Tesseract:
    grayscale -> CLAHE -> resize -> denoise -> Otsu -> deskew -> Otsu
    Returns: binary (single channel)
    """
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"❌ Could not read image: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray2 = clahe.apply(gray)

    h, w = gray2.shape
    if min(h, w) < 600:
        gray2 = cv2.resize(gray2, None, fx=2.0, fy=2.0,
                           interpolation=cv2.INTER_CUBIC)

    gray2 = cv2.fastNlMeansDenoising(gray2, h=10)

    _, binary = cv2.threshold(
        gray2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # invert for text-based angle detection
    binary_inv = 255 - binary
    angle = _compute_skew_angle_from_binary(binary_inv)

    # guardrail against crazy rotations
    if abs(angle) > 15:
        angle = 0.0

    rotated_gray = _rotate_gray(gray2, angle)
    _, final_bin = cv2.threshold(
        rotated_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    _safe_write(debug_dir, "tess_01_gray.png", gray)
    _safe_write(debug_dir, "tess_02_gray_clahe.png", gray2)
    _safe_write(debug_dir, "tess_03_binary.png", binary)
    _safe_write(debug_dir, "tess_04_binary_inv.png", binary_inv)
    _safe_write(debug_dir, "tess_05_rotated_gray.png", rotated_gray)
    _safe_write(debug_dir, "tess_06_final_bin.png", final_bin)

    return final_bin


# Backward compatible wrapper (optional)
def preprocess_image(image_path: str, save_path: str = None, debug: bool = False):
    debug_dir = "debug/preprocess" if debug else None
    processed, _ = preprocess_pipeline(
        image_path,
        debug_dir=debug_dir,
        return_timings=False
    )
    if save_path:
        cv2.imwrite(save_path, processed)
    return processed
