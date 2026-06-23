from pdf_router_v2 import PDFRouter
from common.logger import document_logger
import logging
import sys
from pathlib import Path

# Add src directory to path FIRST before any other imports
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def test_pdf_classification():
    """
    Test the PDF router with sample PDFs
    """
    document_logger.setLevel(logging.DEBUG)

    router = PDFRouter(text_threshold=100)

    # Update these paths to your actual test PDFs
    test_files = {
        "digital": [
            "data/pdfs/digital_sample1.pdf",
            "data/pdfs/digital_sample2.pdf"
        ],
        "scanned": [
            "data/pdfs/scanned_sample1.pdf",
            "data/pdfs/scanned_sample2.pdf"
        ]
    }

    print("\n" + "="*60)
    print("PDF CLASSIFICATION TEST")
    print("="*60 + "\n")

    for expected_type, files in test_files.items():
        print(f"\n--- Testing {expected_type.upper()} PDFs ---")
        for file_path in files:
            if not Path(file_path).exists():
                print(f"⚠️  File not found: {file_path}")
                continue

            try:
                classification, char_count, metadata = router.classify_pdf(
                    file_path)
                status = "✅" if classification == expected_type else "❌"
                print(f"{status} {Path(file_path).name}")
                print(
                    f"   Classification: {classification} | Characters: {char_count}")

            except Exception as e:
                print(f"❌ Error processing {file_path}: {e}")

    print("\n" + "="*60)


if __name__ == "__main__":
    test_pdf_classification()
