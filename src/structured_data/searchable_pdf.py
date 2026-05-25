"""
Searchable PDF Generator: Creates PDFs with OCR text layer.

This allows users to:
- Search within the PDF for text
- Copy text from the PDF
- Have image + text together in one file
"""

import io
from typing import Optional, List, Tuple
from PIL import Image


def create_searchable_pdf_simple(
    image_data: bytes, 
    ocr_text: str, 
    filename: str = "searchable.pdf"
) -> bytes:
    """
    Create a simple searchable PDF from image + OCR text.
    
    Args:
        image_data: Raw image bytes
        ocr_text: Extracted OCR text
        filename: Output filename (for reference)
        
    Returns:
        PDF bytes
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.utils import ImageReader
        from PIL import Image as PILImage
    except ImportError:
        raise ImportError(
            "reportlab not installed. Install with: pip install reportlab"
        )
    
    # Create PDF buffer
    pdf_buffer = io.BytesIO()
    
    # Determine page size from image
    img = PILImage.open(io.BytesIO(image_data))
    img_width, img_height = img.size
    
    # Calculate page size maintaining aspect ratio
    page_size = letter  # 8.5 x 11 inches
    aspect_ratio = img_width / img_height
    
    if aspect_ratio > 1:  # Landscape
        page_size = (11, 8.5 * 72, 11 * 72)  # Width, height in points
    
    # Create PDF canvas
    c = canvas.Canvas(pdf_buffer, pagesize=page_size)
    page_width, page_height = page_size[:2] if isinstance(page_size, tuple) else (page_size[0], page_size[1])
    
    # Draw image
    img_reader = ImageReader(io.BytesIO(image_data))
    c.drawImage(img_reader, 0, 0, width=page_width, height=page_height)
    
    # Add invisible text layer (searchable)
    c.setFont("Helvetica", 8)
    c.setFillAlpha(0)  # Invisible
    
    # Wrap OCR text and place it across the page
    text_lines = ocr_text.split("\n")
    y_position = page_height - 20
    
    for line in text_lines:
        if y_position < 20:
            c.showPage()
            y_position = page_height - 20
        
        # Draw invisible text
        c.drawString(10, y_position, line[:100])  # Limit line length
        y_position -= 12
    
    c.setFillAlpha(1)  # Reset opacity
    c.save()
    
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()


def create_searchable_pdf_pymupdf(
    image_path: str,
    ocr_text: str,
    output_path: str
) -> str:
    """
    Create searchable PDF using PyMuPDF (more robust).
    
    Args:
        image_path: Path to image file
        ocr_text: OCR extracted text
        output_path: Where to save PDF
        
    Returns:
        Success message
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "PyMuPDF not available. Use create_searchable_pdf_simple() instead."
    
    # Create a new PDF document
    doc = fitz.open()
    
    # Insert image as page
    img = fitz.Pixmap(image_path)
    pdfbytes = img.get_pdf_document()
    doc = fitz.open("pdf", pdfbytes)
    
    # Add text layer (searchable)
    page = doc[0]
    page.insert_text((10, 10), ocr_text, fontsize=10, color=(1, 1, 1), alpha=0)
    
    # Save
    doc.save(output_path)
    doc.close()
    
    return f"Searchable PDF created at {output_path}"


def create_searchable_pdf_multipage(
    pages: List[Tuple[bytes, str]]
) -> bytes:
    """
    Create a multi-page searchable PDF from a list of (image_bytes, ocr_text) tuples.
    
    Args:
        pages: List of (image_bytes, ocr_text) tuples for each page.
        
    Returns:
        PDF bytes
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.utils import ImageReader
        from PIL import Image as PILImage
    except ImportError:
        raise ImportError(
            "reportlab not installed. Install with: pip install reportlab"
        )
    
    if not pages:
        return b""
        
    pdf_buffer = io.BytesIO()
    c = None
    
    for img_bytes, ocr_text in pages:
        try:
            img = PILImage.open(io.BytesIO(img_bytes))
            img_width, img_height = img.size
        except Exception:
            continue
            
        # Determine aspect ratio and page size
        page_size = letter
        aspect_ratio = img_width / img_height
        
        if aspect_ratio > 1:  # Landscape
            page_size = (11 * 72, 8.5 * 72)
        else:
            page_size = (8.5 * 72, 11 * 72)
            
        page_width, page_height = page_size
        
        if c is None:
            c = canvas.Canvas(pdf_buffer, pagesize=page_size)
        else:
            c.setPageSize(page_size)
            
        # Draw image
        img_reader = ImageReader(io.BytesIO(img_bytes))
        c.drawImage(img_reader, 0, 0, width=page_width, height=page_height)
        
        # Add invisible text layer (searchable)
        c.setFont("Helvetica", 8)
        c.setFillAlpha(0)  # Invisible
        
        # Wrap OCR text and place it
        text_lines = (ocr_text or "").split("\n")
        y_position = page_height - 20
        
        for line in text_lines:
            if y_position < 20:
                y_position = page_height - 20
            
            c.drawString(10, y_position, line[:120])  # Limit line length
            y_position -= 12
            
        c.setFillAlpha(1)  # Reset opacity
        c.showPage()  # Move to next page
        
    if c is not None:
        c.save()
        
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()


class SearchablePDFGenerator:
    """Generate searchable PDFs with embedded OCR text."""
    
    def __init__(self):
        self.method = "reportlab"  # or "pymupdf"
    
    def generate(
        self,
        image_data: bytes,
        ocr_text: str,
        filename: str = "output.pdf"
    ) -> bytes:
        """
        Generate searchable PDF.
        
        Args:
            image_data: Image bytes
            ocr_text: OCR text to embed
            filename: Output filename
            
        Returns:
            PDF bytes
        """
        try:
            return create_searchable_pdf_simple(image_data, ocr_text, filename)
        except Exception as e:
            raise RuntimeError(f"Failed to create searchable PDF: {e}")
            
    def generate_multipage(
        self,
        pages: List[Tuple[bytes, str]]
    ) -> bytes:
        """
        Generate a multi-page searchable PDF.
        
        Args:
            pages: List of (image_bytes, ocr_text) tuples
            
        Returns:
            PDF bytes
        """
        try:
            return create_searchable_pdf_multipage(pages)
        except Exception as e:
            raise RuntimeError(f"Failed to create multi-page searchable PDF: {e}")
    
    def generate_from_file(
        self,
        image_path: str,
        ocr_text: str,
        output_path: str
    ) -> str:
        """Generate and save searchable PDF."""
        try:
            return create_searchable_pdf_pymupdf(image_path, ocr_text, output_path)
        except Exception as e:
            return f"Error: {e}"

