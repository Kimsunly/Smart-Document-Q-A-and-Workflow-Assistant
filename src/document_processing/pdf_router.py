from common.logger import document_logger
from pypdf import PdfReader
from typing import Tuple, Optional, Dict, Any
import sys
from pathlib import Path
import traceback
import re

# Add src directory to path FIRST before any other imports
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


# Try to import OCR methods
try:
    from document_processing.ocr.pytesseract_ocr import extract_text_from_image
    PYTESSERACT_AVAILABLE = True
except ImportError as e:
    PYTESSERACT_AVAILABLE = False
    document_logger.warning(f"Pytesseract OCR not available: {e}")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    document_logger.warning("EasyOCR not available")

try:
    from PIL import Image
    import pdf2image
    PDF_TO_IMAGE_AVAILABLE = True
except ImportError:
    PDF_TO_IMAGE_AVAILABLE = False
    document_logger.warning("PDF to image conversion not available")


class PDFRouter:
    """
    Intelligent PDF routing system that classifies documents as digital or scanned
    and applies appropriate processing (text extraction or OCR).
    """

    def __init__(self, text_threshold: int = 100):
        """
        Initialize PDFRouter with classification threshold.

        Args:
            text_threshold: Minimum character count to classify as digital PDF (default: 100)
        """
        self.text_threshold = text_threshold
        document_logger.info(
            f"PDFRouter initialized with threshold: {text_threshold} characters"
        )

    def pdf_text_extract(self, file_path) -> str:
        """
        Extract text from PDF using native text layer (no OCR).

        Args:
            file_path: Path to PDF or file-like object

        Returns:
            Extracted text string

        Raises:
            Exception: If PDF reading fails
        """
        try:
            document_logger.debug(
                f"Attempting text extraction from: {file_path}")
            reader = PdfReader(file_path)
            text = ""
            page_count = len(reader.pages)

            document_logger.debug(f"PDF has {page_count} pages")

            for i, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text() or ""
                    text += page_text
                    document_logger.debug(
                        f"Page {i+1}/{page_count}: extracted {len(page_text)} characters"
                    )
                except Exception as page_error:
                    document_logger.warning(
                        f"Error extracting page {i+1}: {str(page_error)}"
                    )
                    continue

            document_logger.info(
                f"Text extraction completed: {len(text)} total characters from {page_count} pages"
            )
            return text

        except FileNotFoundError:
            document_logger.error(f"File not found: {file_path}")
            raise

    def _text_quality_score(self, text: str) -> float:
        """
        Estimate whether extracted PDF text looks readable or like OCR garbage.
        Returns a score in [0, 1], where higher means more trustworthy.
        """
        normalized = (text or "").strip()
        if not normalized:
            return 0.0

        length = len(normalized)
        alpha_num = sum(1 for ch in normalized if ch.isalnum())
        printable = sum(1 for ch in normalized if ch.isprintable())
        weird = sum(1 for ch in normalized if ch in "|_-=+*~`^{}[]<>\\/")
        words = re.findall(r"[A-Za-z0-9\u1780-\u17ff']+", normalized)

        alpha_ratio = alpha_num / max(length, 1)
        printable_ratio = printable / max(length, 1)
        weird_ratio = weird / max(length, 1)
        word_density = min(len(words) / max(length / 20.0, 1.0), 1.0)

        score = (
            alpha_ratio * 0.45
            + printable_ratio * 0.25
            + word_density * 0.30
            - weird_ratio * 0.35
        )
        return max(0.0, min(1.0, score))

    def classify_pdf(self, file_path) -> Tuple[str, int, Dict[str, Any]]:
        """
        Classify PDF as 'digital' or 'scanned' based on extracted text volume.

        Args:
            file_path: Path to PDF file

        Returns:
            Tuple of (classification, char_count, metadata_dict)

        Raises:
            Exception: If classification fails
        """
        try:
            document_logger.info(
                f"Starting PDF classification for: {file_path}")

            # Extract per-page text stats first. If any page has no text layer,
            # treat document as scanned to force OCR path.
            reader = PdfReader(file_path)
            page_char_counts = []
            text_fragments = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                stripped = page_text.strip()
                page_char_counts.append(len(stripped))
                text_fragments.append(page_text)

            text = "".join(text_fragments)
            char_count = len(text.strip())
            page_count = len(page_char_counts)
            zero_text_pages = sum(1 for n in page_char_counts if n == 0)
            text_quality = self._text_quality_score(text)

            # Route to OCR when any page appears image-only or the text layer
            # looks like OCR garbage / low-quality extraction.
            if zero_text_pages > 0 or (char_count >= self.text_threshold and text_quality < 0.45):
                classification = "scanned"
            else:
                classification = "digital" if char_count >= self.text_threshold else "scanned"

            # Prepare metadata
            metadata = {
                "file": str(file_path),
                "char_count": char_count,
                "page_count": page_count,
                "zero_text_pages": zero_text_pages,
                "page_char_counts": page_char_counts,
                "text_quality_score": round(text_quality, 3),
                "threshold": self.text_threshold,
                "classification": classification,
                "confidence": "high" if (char_count >= self.text_threshold * 2 or char_count < self.text_threshold // 2) else "medium"
            }

            document_logger.info(
                f"Classification Result - {classification.upper()}: "
                f"Characters: {char_count}, Threshold: {self.text_threshold}"
            )

            return classification, char_count, metadata

        except Exception as e:
            document_logger.error(
                f"Classification failed for {file_path}: {str(e)}",
                exc_info=True
            )
            raise

    def ocr_pdf_pages(self, file_path: str, ocr_method: str = "pytesseract") -> str:
        """
        Process scanned PDF pages using OCR.

        Args:
            file_path: Path to PDF file
            ocr_method: OCR method to use ('pytesseract' or 'easyocr')

        Returns:
            Extracted text from OCR

        Raises:
            NotImplementedError: If OCR method not available
            Exception: If OCR processing fails
        """
        try:
            document_logger.info(
                f"Starting OCR processing for: {file_path} using {ocr_method}"
            )

            if ocr_method == "pytesseract":
                if not PYTESSERACT_AVAILABLE:
                    document_logger.error("Pytesseract OCR not available")
                    raise ImportError("Pytesseract OCR is not installed")

                return self._ocr_with_pytesseract(file_path)

            elif ocr_method == "easyocr":
                return self._ocr_with_easyocr(file_path)

            else:
                raise ValueError(f"Unknown OCR method: {ocr_method}")

        except Exception as e:
            document_logger.error(
                f"OCR processing failed for {file_path}: {str(e)}",
                exc_info=True
            )
            raise

    def _ocr_with_pytesseract(self, file_path: str, lang_mode: str = "eng") -> str:
        """
        Internal method to perform OCR using Pytesseract.

        Args:
            file_path: Path to PDF file
            lang_mode: Language mode ('eng', 'khm', 'eng+khm')

        Returns:
            Extracted text
        """
        try:
            document_logger.debug(
                f"Converting PDF to images for Pytesseract OCR: {file_path}")

            if not PDF_TO_IMAGE_AVAILABLE:
                raise ImportError(
                    "pdf2image not installed. Install with: pip install pdf2image")

            from pdf2image import convert_from_path

            # Convert PDF pages to images
            images = convert_from_path(file_path)
            document_logger.debug(f"Converted {len(images)} pages to images")

            all_text = ""
            for i, image in enumerate(images):
                try:
                    # Save image temporarily
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        temp_image_path = tmp.name
                        image.save(temp_image_path, "PNG")

                    # Extract text from image
                    cleaned_text, _, raw_text, confidence = extract_text_from_image(
                        temp_image_path, lang_mode=lang_mode)
                    all_text += cleaned_text + "\n"

                    document_logger.debug(
                        f"Page {i+1}: OCR confidence: {confidence:.1f}%, extracted {len(cleaned_text)} characters"
                    )

                    # Cleanup
                    Path(temp_image_path).unlink(missing_ok=True)

                except Exception as page_error:
                    document_logger.warning(
                        f"OCR failed for page {i+1}: {str(page_error)}"
                    )
                    continue

            document_logger.info(
                f"Pytesseract OCR completed: {len(all_text)} total characters"
            )
            return all_text

        except Exception as e:
            document_logger.error(
                f"Pytesseract OCR failed: {str(e)}", exc_info=True)
            raise

    def _ocr_with_easyocr(self, file_path: str) -> str:
        """
        Internal method to perform OCR using EasyOCR (faster and more accurate).

        Args:
            file_path: Path to PDF file

        Returns:
            Extracted text
        """
        try:
            document_logger.debug(
                f"Converting PDF to images for EasyOCR: {file_path}")

            if not EASYOCR_AVAILABLE:
                raise ImportError(
                    "EasyOCR not installed. Install with: pip install easyocr")

            if not PDF_TO_IMAGE_AVAILABLE:
                raise ImportError(
                    "pdf2image not installed. Install with: pip install pdf2image")

            from pdf2image import convert_from_path

            # Convert PDF pages to images
            images = convert_from_path(file_path)
            document_logger.debug(f"Converted {len(images)} pages to images")

            # Initialize EasyOCR reader (English)
            reader = easyocr.Reader(['en'], gpu=False)
            document_logger.debug("EasyOCR reader initialized")

            all_text = ""
            for i, image in enumerate(images):
                try:
                    # Save image temporarily
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        temp_image_path = tmp.name
                        image.save(temp_image_path, "PNG")

                    # Extract text using EasyOCR
                    results = reader.readtext(temp_image_path)

                    # Combine text from all detections
                    page_text = "\n".join([detection[1]
                                          for detection in results])
                    all_text += page_text + "\n"

                    # Calculate confidence
                    confidences = [detection[2] for detection in results]
                    avg_confidence = (
                        sum(confidences) / len(confidences) * 100) if confidences else 0

                    document_logger.debug(
                        f"Page {i+1}: EasyOCR confidence: {avg_confidence:.1f}%, extracted {len(page_text)} characters"
                    )

                    # Cleanup
                    Path(temp_image_path).unlink(missing_ok=True)

                except Exception as page_error:
                    document_logger.warning(
                        f"EasyOCR failed for page {i+1}: {str(page_error)}"
                    )
                    continue

            document_logger.info(
                f"EasyOCR completed: {len(all_text)} total characters"
            )
            return all_text

        except Exception as e:
            document_logger.error(f"EasyOCR failed: {str(e)}", exc_info=True)
            raise

    def _extract_page_texts(self, file_path: str):
        """
        Extract per-page native text and a readability score.
        Returns a list of dicts with page index, text, score, and route decision.
        """
        reader = PdfReader(file_path)
        pages = []
        for index, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            stripped = page_text.strip()
            score = self._text_quality_score(stripped)
            pages.append({
                "page_index": index,
                "text": page_text,
                "char_count": len(stripped),
                "text_quality_score": round(score, 3),
                "needs_ocr": len(stripped) == 0 or score < 0.45,
            })
        return pages

    def _ocr_pdf_page_images(self, file_path: str, lang_mode: str = "eng"):
        """
        OCR every PDF page by rendering it to images.
        Returns page-wise text so mixed documents can be combined with text-layer pages.
        """
        if not PDF_TO_IMAGE_AVAILABLE:
            raise ImportError(
                "pdf2image not installed. Install with: pip install pdf2image")

        from pdf2image import convert_from_path
        import tempfile

        images = convert_from_path(file_path)
        page_texts = []
        for index, image in enumerate(images):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_image_path = tmp.name
                image.save(temp_image_path, "PNG")

            try:
                cleaned_text, _, raw_text, confidence = extract_text_from_image(
                    temp_image_path,
                    lang_mode=lang_mode,
                    debug=False,
                )
                page_texts.append({
                    "page_index": index,
                    "text": cleaned_text,
                    "raw_text": raw_text,
                    "confidence": confidence,
                })
            finally:
                Path(temp_image_path).unlink(missing_ok=True)

        return page_texts

    def route_pdf(self, file_path: str, apply_ocr: bool = True, lang_mode: str = "eng"):
        """
        Route PDF automatically:
        - Digital PDF → text extraction
        - Scanned PDF → OCR

        Args:
            file_path: Path to PDF file
            apply_ocr: Whether to apply OCR for scanned documents (default: True)
            lang_mode: Language mode for OCR ('eng', 'khm', 'eng+khm') (default: 'eng')

        Returns:
            Tuple of (text_content, processing_method, metadata)
        """
        try:
            document_logger.info(f"Routing PDF: {file_path}")

            classification, char_count, metadata = self.classify_pdf(file_path)
            page_texts = self._extract_page_texts(file_path)
            ocr_page_indexes = [p["page_index"]
                                for p in page_texts if p["needs_ocr"]]
            digital_page_indexes = [p["page_index"]
                                    for p in page_texts if not p["needs_ocr"]]

            # If the whole document looks clean, keep native text extraction.
            if not ocr_page_indexes:
                text = self.pdf_text_extract(file_path)
                metadata["processing_method"] = "text_extraction"
                metadata["success"] = True
                metadata["mixed_pages"] = 0
                return text, "text_extraction", metadata

            if not apply_ocr:
                metadata["processing_method"] = "ocr_skipped"
                metadata["success"] = False
                metadata["mixed_pages"] = len(ocr_page_indexes)
                return "", "ocr_skipped", metadata

            # Mixed routing: keep readable text pages, OCR the rest.
            if digital_page_indexes and ocr_page_indexes:
                document_logger.info(
                    f"Using mixed routing: {len(digital_page_indexes)} text pages, {len(ocr_page_indexes)} OCR pages"
                )
                if not PDF_TO_IMAGE_AVAILABLE:
                    raise ImportError(
                        "pdf2image not installed. Install with: pip install pdf2image")

                from pdf2image import convert_from_path
                import tempfile

                images = convert_from_path(file_path)
                combined_pages = []
                for index, page in enumerate(page_texts):
                    if page["needs_ocr"]:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            temp_image_path = tmp.name
                            images[index].save(temp_image_path, "PNG")
                        try:
                            cleaned_text, _, raw_text, confidence = extract_text_from_image(
                                temp_image_path,
                                lang_mode=lang_mode,
                                debug=False,
                            )
                            combined_pages.append(cleaned_text)
                        finally:
                            Path(temp_image_path).unlink(missing_ok=True)
                    else:
                        combined_pages.append(page["text"].strip())

                text = "\n\n".join(t for t in combined_pages if t.strip())
                metadata["processing_method"] = "mixed_text_plus_ocr"
                metadata["success"] = True
                metadata["mixed_pages"] = len(ocr_page_indexes)
                metadata["text_pages"] = len(digital_page_indexes)
                return text, "mixed_text_plus_ocr", metadata

            # Otherwise treat as a scanned document and OCR all pages.
            if EASYOCR_AVAILABLE:
                document_logger.info("Using EasyOCR")
                text = self._ocr_with_easyocr(file_path)
                method = "ocr_easyocr"
            else:
                document_logger.info("Using Pytesseract")
                text = self._ocr_with_pytesseract(
                    file_path, lang_mode=lang_mode)
                method = "ocr_pytesseract"

            metadata["processing_method"] = method
            metadata["success"] = True
            metadata["mixed_pages"] = len(ocr_page_indexes)
            return text, method, metadata

        except Exception as e:
            document_logger.error(f"Routing failed: {str(e)}", exc_info=True)
            raise
