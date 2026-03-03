from common.logger import document_logger
from pypdf import PdfReader
from typing import Tuple, Optional, Dict, Any
import sys
from pathlib import Path
import traceback

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
        except Exception as e:
            document_logger.error(
                f"Text extraction failed for {file_path}: {str(e)}",
                exc_info=True
            )
            raise

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

            # Extract text
            text = self.pdf_text_extract(file_path)
            char_count = len(text.strip())

            # Classification logic based on threshold
            classification = "digital" if char_count >= self.text_threshold else "scanned"

            # Prepare metadata
            metadata = {
                "file": str(file_path),
                "char_count": char_count,
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

    def _ocr_with_pytesseract(self, file_path: str) -> str:
        """
        Internal method to perform OCR using Pytesseract.

        Args:
            file_path: Path to PDF file

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
                    temp_image_path = f"/tmp/page_{i}.png"
                    image.save(temp_image_path, "PNG")

                    # Extract text from image
                    cleaned_text, _, raw_text, confidence = extract_text_from_image(
                        temp_image_path)
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
        """
        Main routing method: classifies PDF and applies appropriate processing.

        Args:
            file_path: Path to PDF file
            apply_ocr: Whether to apply OCR for scanned documents (default: True)

        Returns:
            Tuple of (text_content, processing_method, metadata)

        Raises:
            Exception: If routing or processing fails
        """
        try:
            document_logger.info(f"Starting PDF routing for: {file_path}")

            # Classify the PDF
            classification, char_count, metadata = self.classify_pdf(file_path)

            if classification == "digital":
                # Digital PDF - use text extraction
                document_logger.info(
                    f"Routing to TEXT EXTRACTION: {file_path}")
                text = self.pdf_text_extract(file_path)
                metadata["processing_method"] = "text_extraction"
                metadata["success"] = True
                return text, "text_extraction", metadata

            elif classification == "scanned":
                # Scanned PDF - requires OCR
                if not apply_ocr:
                    document_logger.warning(
                        f"Scanned PDF detected but OCR disabled: {file_path}"
                    )
                    metadata["processing_method"] = "ocr_skipped"
                    metadata["success"] = False
                    return "", "ocr_skipped", metadata

                document_logger.warning(
                    f"Routing to OCR: {file_path} (low text: {char_count} chars)"
                )
                try:
                    # Try EasyOCR first (better quality and speed)
                    if EASYOCR_AVAILABLE:
                        document_logger.info("Using EasyOCR for scanned PDF")
                        text = self.ocr_pdf_pages(
                            file_path, ocr_method="easyocr")
                        metadata["processing_method"] = "ocr_easyocr"
                    else:
                        # Fallback to Pytesseract
                        document_logger.info(
                            "Using Pytesseract OCR (EasyOCR not available)")
                        text = self.ocr_pdf_pages(
                            file_path, ocr_method="pytesseract")
                        metadata["processing_method"] = "ocr_pytesseract"

                    metadata["success"] = True
                    return text, metadata["processing_method"], metadata
                except Exception as ocr_error:
                    document_logger.error(
                        f"OCR failed, may need manual review: {str(ocr_error)}"
                    )
                    metadata["processing_method"] = "ocr_failed"
                    metadata["success"] = False
                    metadata["error"] = str(ocr_error)
                    raise

        except FileNotFoundError as e:
            document_logger.error(
                f"File not found during routing: {file_path}", exc_info=True)
            raise
        except Exception as e:
            document_logger.error(
                f"PDF routing failed for {file_path}: {str(e)}",
                exc_info=True
            )
            raise
