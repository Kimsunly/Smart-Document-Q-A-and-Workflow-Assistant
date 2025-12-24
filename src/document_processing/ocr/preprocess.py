# src/document_processing/ocr/preprocess.py

import cv2
import numpy as np


def preprocess_image(image_path, save_path=None, debug=False):
    """
    Preprocess the image for OCR:
    - grayscale
    - denoise
    - threshold
    - deskew
    """

    # Load image
    img = cv2.imread(image_path)

    if img is None:
        raise ValueError(f"❌ Could not read image: {image_path}")

    # Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Denoise
    denoised = cv2.medianBlur(gray, 3)

    # Adaptive threshold
    binarized = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )

    # Deskew
    coords = np.column_stack(np.where(binarized > 0))
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    (h, w) = binarized.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    deskewed = cv2.warpAffine(
        binarized, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )

    # Debug mode: save images for inspection
    if debug:
        cv2.imwrite("debug_original.png", img)
        cv2.imwrite("debug_gray.png", gray)
        cv2.imwrite("debug_denoised.png", denoised)
        cv2.imwrite("debug_binarized.png", binarized)
        cv2.imwrite("debug_deskewed.png", deskewed)
        print("🔍 Debug images saved in project folder.")

    # Save final processed image
    if save_path:
        cv2.imwrite(save_path, deskewed)

    return deskewed
