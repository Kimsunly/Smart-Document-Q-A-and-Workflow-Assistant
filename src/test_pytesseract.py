#!/usr/bin/env python
"""Task 9: Test Pytesseract OCR accuracy with scanned PDFs"""
from common.logger import document_logger
from PIL import Image
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# Create a scanned PDF from existing image
print("Task 9: Testing Pytesseract OCR Accuracy")
print("="*80 + "\n")

# Check if image exists
image_path = Path(__file__).parent.parent / "data" / \
    "images_for_ocr_test" / "image.png"

if image_path.exists():
    print(f"✅ Found test image: {image_path}")
    print("\nConverting image to PDF for OCR testing...")

    # Create a simple PDF from image
    from PIL import Image
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    import io

    try:
        # Open image
        img = Image.open(image_path)

        # Create PDF with image
        pdf_path = Path(__file__).parent.parent / "data" / \
            "pdfs" / "scanned_sample1.pdf"

        # Convert to PDF using PIL
        if img.mode == 'RGBA':
            img = img.convert('RGB')

        img.save(str(pdf_path), 'PDF')
        print(f"✅ Created scanned PDF: {pdf_path}\n")

        # Now test the router with this scanned PDF
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pdf_router", "document_processing/pdf_router.py")
        pdf_router = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pdf_router)

        router = pdf_router.PDFRouter(text_threshold=100)
        document_logger.setLevel(logging.DEBUG)

        print("Testing Pytesseract OCR on scanned PDF...")
        print("-"*80)

        try:
            # Test with OCR
            text, method, metadata = router.route_pdf(
                str(pdf_path), apply_ocr=True)

            print(f"\n✅ OCR Test Results:")
            print(f"   Classification: {metadata.get('classification')}")
            print(
                f"   Extracted Characters: {metadata.get('char_count')} (native text)")
            print(f"   Processing Method: {method}")
            print(f"   Success: {metadata.get('success')}")
            print(f"   OCR Text Length: {len(text)} characters")

            if len(text) > 0:
                print(f"   Sample OCR Output (first 200 chars):")
                print(f"   {text[:200]}...")
                print(f"\n✅ Pytesseract OCR is working!")
            else:
                print(f"\n⚠️  No text extracted via OCR")

        except ImportError as e:
            print(f"\n⚠️  OCR libraries not installed:")
            print(f"   {str(e)}")
            print(f"\n   Install with:")
            print(f"   pip install pytesseract pdf2image pillow")
            print(f"   pip install easyocr (optional, for better performance)")

        except Exception as e:
            print(f"\n❌ Error during OCR test: {str(e)}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"❌ Error creating test PDF: {str(e)}")
        import traceback
        traceback.print_exc()
else:
    print(f"⚠️  Test image not found at: {image_path}")
    print("\nTo complete Task 9, you need:")
    print("1. Place a scanned document image in: data/images_for_ocr_test/")
    print("2. Or manually test with: python -c \"...\" in src directory")

print("\n" + "="*80)
