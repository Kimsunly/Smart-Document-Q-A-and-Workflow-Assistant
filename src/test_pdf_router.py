#!/usr/bin/env python
"""Final test script for PDF Router - Run from src directory"""
import importlib.util
from common.logger import document_logger
import logging
import sys
from pathlib import Path

# Ensure src is in path
src = Path(__file__).parent
if str(src) not in sys.path:
    sys.path.insert(0, str(src))


# Import from document_processing using absolute import
router_path = (src / "document_processing" / "pdf_router.py")
spec = importlib.util.spec_from_file_location("pdf_router", router_path)
pdf_router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf_router)
PDFRouter = pdf_router.PDFRouter


def test_pdf_classification():
    """
    Test the PDF router with sample PDFs
    """
    document_logger.setLevel(logging.DEBUG)

    print("\n" + "="*80)
    print("PDF CLASSIFICATION & ROUTING TEST")
    print("="*80 + "\n")

    router = PDFRouter(text_threshold=100)

    # Get absolute paths
    base_dir = Path(__file__).parent.parent
    pdf_dir = base_dir / "data" / "pdfs"

    # Test PDF files
    test_files = {
        "digital": [
            pdf_dir / "digital_sample1.pdf",
            pdf_dir / "digital_sample2.pdf"
        ],
        "other": [
            pdf_dir / "machine_learning_demo.pdf",
            pdf_dir / "KIMSUN_Resume_and_CoverLetter.pdf"
        ]
    }

    results = {
        "success": 0,
        "failed": 0,
        "not_found": 0,
        "details": []
    }

    for expected_type, files in test_files.items():
        print(f"\n{'-'*80}")
        print(f"Testing {expected_type.upper()} PDFs")
        print(f"{'-'*80}")

        for file_path in files:
            file_obj = Path(file_path)

            if not file_obj.exists():
                print(f"⚠️  NOT FOUND: {file_path}")
                results["not_found"] += 1
                results["details"].append({
                    "file": file_path,
                    "status": "not_found",
                    "expected": expected_type
                })
                continue

            try:
                # Run the full routing
                text, method, metadata = router.route_pdf(file_path)

                classification = metadata.get("classification")
                char_count = metadata.get("char_count")
                confidence = metadata.get("confidence")
                success = metadata.get("success")

                # Check if classification matches expectation
                matches = classification == expected_type
                status_icon = "✅" if matches else "❌"

                print(f"\n{status_icon} {file_obj.name}")
                print(f"   Expected: {expected_type.upper()}")
                print(f"   Got: {classification.upper()}")
                print(f"   Characters: {char_count}")
                print(f"   Confidence: {confidence}")
                print(f"   Method: {method}")
                print(f"   Success: {success}")
                print(f"   Text extracted: {len(text)} characters")

                if matches and success:
                    results["success"] += 1
                else:
                    results["failed"] += 1

                results["details"].append({
                    "file": file_path,
                    "expected": expected_type,
                    "classification": classification,
                    "method": method,
                    "success": success,
                    "matches": matches
                })

            except Exception as e:
                print(f"❌ ERROR: {file_obj.name}")
                print(f"   Error: {str(e)}")
                results["failed"] += 1
                results["details"].append({
                    "file": file_path,
                    "status": "error",
                    "expected": expected_type,
                    "error": str(e)
                })

    # Summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successful: {results['success']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"⚠️  Not Found: {results['not_found']}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    test_pdf_classification()
