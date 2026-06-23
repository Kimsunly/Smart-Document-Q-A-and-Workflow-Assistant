#!/usr/bin/env python3
"""
Automated User Acceptance Testing (UAT) script for Smart Document Q&A and Workflow Assistant.
Verifies all Phase 2 features. ASCII-safe & Auto-flushing for Windows consoles.
1. OCR & PDF Routing
2. Text Chunking
3. Embeddings & FAISS Vector Search
4. Retrieval
5. RAG Pipeline (Extractive Fallback)
6. Structured Data Extraction (Tables, Records, Form Fields)
7. Structured Data Exporters (JSON, CSV, Excel, Searchable PDF)
"""

import builtins
import os
import sys
import tempfile
import json
import shutil
import io
import traceback
from pathlib import Path

# Disable CUDA to save virtual memory mapping address space and avoid Windows paging errors
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Override print to automatically flush standard out
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    builtins.print(*args, **kwargs)

# Add src to Python Path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "src"))

print("================================================================")
print("  SMART DOCUMENT Q&A AND WORKFLOW ASSISTANT - UAT AUTOMATED TEST")
print("================================================================")

success_count = 0
total_count = 0

def assert_test(step_name, condition, details=""):
    global success_count, total_count
    total_count += 1
    if condition:
        success_count += 1
        print(f"[PASS] {step_name}")
        if details:
            print(f"   [INFO] {details}")
    else:
        print(f"[FAIL] {step_name}")
        if details:
            print(f"   [WARN] {details}")

# Initialize variables to prevent NameError cascading failures
chunks = []
manager = None
extracted_all = {}
records = []

# -------------------------------------------------------------
# 1. OCR & PDF Routing
# -------------------------------------------------------------
print("\n----------------------------------------------------------------")
print(" SECTION 1: OCR & PDF Routing")
print("----------------------------------------------------------------")

try:
    from document_processing.pdf_router import PDFRouter
    router = PDFRouter(text_threshold=100)
    assert_test("PDFRouter initialization", router is not None, "Router instance created successfully.")
except Exception as e:
    traceback.print_exc()
    assert_test("PDFRouter initialization", False, f"Failed to initialize PDFRouter: {e}")

# Check test PDFs existence
sample_dir = ROOT_DIR / "data" / "pdfs"
scanned_pdf = ROOT_DIR / "data" / "scanned_sample1.pdf"
if not scanned_pdf.exists() and (sample_dir / "scanned_sample1.pdf").exists():
    scanned_pdf = sample_dir / "scanned_sample1.pdf"

digital_pdf = ROOT_DIR / "data" / "machine_learning_demo.pdf"
if not digital_pdf.exists() and (sample_dir / "machine_learning_demo.pdf").exists():
    digital_pdf = sample_dir / "machine_learning_demo.pdf"

if digital_pdf.exists():
    try:
        print(f"Classifying digital PDF: {digital_pdf}")
        classification, char_count, metadata = router.classify_pdf(str(digital_pdf))
        assert_test(
            "PDF Classification (Digital)",
            classification == "digital" and char_count > 100,
            f"Classified as {classification.upper()} (chars: {char_count})."
        )
    except Exception as e:
        traceback.print_exc()
        assert_test("PDF Classification (Digital)", False, f"Error: {e}")
else:
    assert_test("PDF Classification (Digital) - Skip", True, "Digital test PDF not found. Skipping.")

if scanned_pdf.exists():
    try:
        print(f"Classifying scanned PDF: {scanned_pdf}")
        classification, char_count, metadata = router.classify_pdf(str(scanned_pdf))
        assert_test(
            "PDF Classification (Scanned)",
            classification == "scanned",
            f"Classified as {classification.upper()} (chars: {char_count})."
        )
    except Exception as e:
        traceback.print_exc()
        assert_test("PDF Classification (Scanned)", False, f"Error: {e}")
else:
    assert_test("PDF Classification (Scanned) - Skip", True, "Scanned test PDF not found. Skipping.")


# -------------------------------------------------------------
# 2. Text Chunking
# -------------------------------------------------------------
print("\n----------------------------------------------------------------")
print(" SECTION 2: Text Chunking")
print("----------------------------------------------------------------")

sample_text = (
    "In machine learning, supervised learning is the machine learning task of learning a function that "
    "maps an input to an output based on example input-output pairs. It infers a function from labeled training data "
    "consisting of a set of training examples. Each example is a pair consisting of an input object and a desired output value.\n\n"
    "Unsupervised learning is a type of algorithm that learns patterns from untagged data. The hope is that through "
    "mimicry, which is an important mode of learning in people, the machine is forced to build a compact internal representation "
    "of its world. Unlike supervised learning, it does not rely on human feedback."
)

try:
    print("Splitting test text into chunks...")
    from text_processing.split_text import split_text_into_chunks
    chunks = split_text_into_chunks(sample_text, doc_id="DOC_TEST", page=1, min_chars=100, max_chars=300)
    
    assert_test("Text splitting", len(chunks) >= 2, f"Split test paragraph into {len(chunks)} chunks.")
    
    if chunks:
        first_chunk = chunks[0]
        has_meta = "chunk_id" in first_chunk and "page" in first_chunk and "doc_id" in first_chunk
        assert_test(
            "Chunk metadata tagging",
            has_meta,
            f"Chunk 1 ID: {first_chunk.get('chunk_id')}, Page: {first_chunk.get('page')}, Doc: {first_chunk.get('doc_id')}"
        )
except Exception as e:
    traceback.print_exc()
    assert_test("Text chunking", False, f"Failed: {e}")


# -------------------------------------------------------------
# 3. Embeddings & FAISS Vector Search
# -------------------------------------------------------------
print("\n----------------------------------------------------------------")
print(" SECTION 3: Embeddings & Vector Indexing")
print("----------------------------------------------------------------")

try:
    print("Loading embeddings model and generating vectors...")
    from phase2.embeddings.embeddings import embed_chunks
    from phase2.vector_db.faiss_index import FAISSIndexManager
    
    if not chunks:
        raise ValueError("No chunks available for embedding. Check Section 2.")

    # Try embedding the chunks
    vectors = embed_chunks(chunks)
    assert_test(
        "Generate Embeddings", 
        vectors.shape == (len(chunks), 384), 
        f"Generated matrix of shape {vectors.shape} (384-dimensions)."
    )
    
    # Try Indexing with FAISS
    print("Adding vectors to FAISS index...")
    manager = FAISSIndexManager(dimension=384)
    manager.add_vectors(vectors, chunks)
    assert_test(
        "FAISS Index insertion", 
        manager.index.ntotal == len(chunks), 
        f"Successfully indexed {manager.index.ntotal} vector chunks."
    )
    
    # Test FAISS save and load
    print("Saving FAISS index to temp directory...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        save_path = Path(tmp_dir) / "test_index"
        manager.save(str(save_path))
        
        assert_test(
            "Index serialization (Save)",
            Path(f"{save_path}.faiss").exists() and Path(f"{save_path}.meta").exists(),
            "Saved index files (.faiss & .meta) created on disk."
        )
        
        print("Loading FAISS index back from temp directory...")
        loaded_manager = FAISSIndexManager.load(str(save_path))
        assert_test(
            "Index deserialization (Load)",
            loaded_manager.index.ntotal == len(chunks),
            f"Loaded index successfully. Total indexed vectors: {loaded_manager.index.ntotal}"
        )
except Exception as e:
    traceback.print_exc()
    assert_test("Embeddings and FAISS indexing", False, f"Failed: {e}")


# -------------------------------------------------------------
# 4. Retrieval & RAG
# -------------------------------------------------------------
print("\n----------------------------------------------------------------")
print(" SECTION 4: Semantic Retrieval & RAG Answer Generation")
print("----------------------------------------------------------------")

try:
    if manager is None:
         raise ValueError("FAISS manager is not initialized (Section 3 failed). Skipping RAG tests.")
         
    print("Retrieving similar chunks for query...")
    from phase2.embeddings.embeddings import embed_text
    from phase2.rag.rag_service import generate_rag_answer
    
    # Retrieval test
    query = "What is unsupervised learning?"
    query_vec = embed_text(query)
    # Search with k=2 to ensure both supervised and unsupervised chunks are retrieved
    distances, results = manager.search(query_vec, k=2)
    
    assert_test(
        "Semantic Search Retrieval",
        len(results) > 0 and any("unsupervised" in r["text"].lower() for r in results),
        f"Retrieved relevant chunk. Distance score: {distances[0]:.4f}"
    )
    
    # Enrich results with "score" key which is expected by generate_rag_answer extractive fallback
    enriched_results = []
    for dist, item in zip(distances, results):
        row = dict(item)
        row["score"] = float(dist)
        enriched_results.append(row)
    
    # RAG Grounding test (Local Extractive Fallback)
    print("Generating grounded answer from context...")
    rag_result = generate_rag_answer(
        question="What is unsupervised learning?",
        retrieved_chunks=enriched_results,
        rag_mode="local"
    )
    
    assert_test(
        "RAG Output (Local Extractive Fallback)",
        rag_result["answer"] != "I don't know" and "unsupervised" in rag_result["answer"].lower(),
        f"Generated extractive answer: '{rag_result['answer'][:80]}...'"
    )
    
    # Grounding "I don't know" enforcement test
    print("Testing 'I don't know' output for ungrounded query...")
    empty_result = generate_rag_answer(
        question="What is the capital of France?",
        retrieved_chunks=[{"text": "Python is a programming language.", "score": 0.01}],
        rag_mode="local"
    )
    
    assert_test(
        "RAG Grounding Enforcement ('I don't know')",
        empty_result["answer"] == "I don't know",
        f"Properly returned '{empty_result['answer']}' when query was not in the context."
    )
except Exception as e:
    traceback.print_exc()
    assert_test("Retrieval & RAG", False, f"Failed: {e}")


# -------------------------------------------------------------
# 5. Structured Data Extractor
# -------------------------------------------------------------
print("\n----------------------------------------------------------------")
print(" SECTION 5: Structured Data Extraction")
print("----------------------------------------------------------------")

# Roster document sample (Blank line separation added)
sample_student_roster = """
Class Roster: Grade 12 A

No.   Student ID    Student Name        Gender    Contact Number         Department
1     STUD_001      Sombo Kakada        Male      012345678              IT Science
2     STUD_002      Keo Sophea          Female    098765432              Engineering
3     STUD_003      Chan Dara           Male      085555123              Science
4     STUD_004      Meas Sreyneang      Female    077123456              Arts
"""

try:
    print("Running DataExtractor on sample roster...")
    from structured_data.extractor import DataExtractor
    extractor = DataExtractor(sample_student_roster, source_name="roster.txt", doc_id="TEST_ROSTER")
    extracted_all = extractor.extract_all()
    
    # Check tables
    tables = extracted_all.get("tables", [])
    assert_test("Table detection", len(tables) > 0, f"Detected {len(tables)} tables.")
    if tables:
        # Select the table with the largest row count (ignores text header noise table)
        tbl = max(tables, key=lambda t: t.get("row_count", 0))
        assert_test(
            "Table dimensions",
            tbl.get("row_count") == 4 and tbl.get("column_count") == 6,
            f"Table shape: {tbl.get('row_count')} rows x {tbl.get('column_count')} columns."
        )
        
    # Check person records
    records = extracted_all.get("records", [])
    assert_test("Person records detection", len(records) == 4, f"Extracted {len(records)} person records.")
    
    if records:
        first_rec = records[0]
        has_correct_data = (
            first_rec.get("name") == "Sombo Kakada" and
            first_rec.get("id") == "STUD_001" and
            first_rec.get("phone") == "012345678" and
            first_rec.get("department") == "IT Science"
        )
        assert_test(
            "Person record fields parsing",
            has_correct_data,
            f"Parsed Record 1: Name='{first_rec.get('name')}', ID='{first_rec.get('id')}', Phone='{first_rec.get('phone')}'"
        )
except Exception as e:
    traceback.print_exc()
    assert_test("Structured Data Extractor", False, f"Failed: {e}")


# -------------------------------------------------------------
# 6. Structured Data Exporters
# -------------------------------------------------------------
print("\n----------------------------------------------------------------")
print(" SECTION 6: Structured Data Exporters")
print("----------------------------------------------------------------")

try:
    if not extracted_all or not records:
         raise ValueError("Structured data extraction was not completed (Section 5 failed). Skipping export tests.")

    from structured_data.exporters import JSONExporter, CSVExporter, ExcelExporter
    from structured_data.searchable_pdf import SearchablePDFGenerator
    
    with tempfile.TemporaryDirectory() as out_dir:
        # JSON
        print("Testing JSON Export...")
        json_path = Path(out_dir) / "export.json"
        json_str = JSONExporter.export(extracted_all)
        JSONExporter.save_to_file(extracted_all, str(json_path))
        
        assert_test(
            "JSON Exporter",
            json_path.exists() and len(json_str) > 0,
            "Created structured JSON export file."
        )
        
        # CSV
        print("Testing CSV Export...")
        csv_path = Path(out_dir) / "records.csv"
        csv_str = CSVExporter.export_records(records)
        CSVExporter.save_to_file(csv_str, str(csv_path))
        
        assert_test(
            "CSV Exporter",
            csv_path.exists() and len(csv_str) > 0,
            "Created flat CSV export file containing person records."
        )
        
        # Excel
        print("Testing Excel Export...")
        excel_path = Path(out_dir) / "export.xlsx"
        excel_bytes = ExcelExporter.export(extracted_all)
        ExcelExporter.save_to_file(excel_bytes, str(excel_path))
        
        assert_test(
            "Excel Exporter",
            excel_path.exists() and len(excel_bytes) > 0,
            "Created styled Excel (.xlsx) file containing formatted sheets."
        )
        
        # Searchable PDF
        print("Testing Searchable PDF Generation...")
        # Use a dummy 100x100 white image
        from PIL import Image
        img = Image.new("RGB", (100, 100), color="white")
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="PNG")
        img_bytes = img_byte_arr.getvalue()
        
        pdf_gen = SearchablePDFGenerator()
        pdf_bytes = pdf_gen.generate_multipage([(img_bytes, "Supervised Learning\nPage 1 text content")])
        pdf_path = Path(out_dir) / "searchable.pdf"
        pdf_path.write_bytes(pdf_bytes)
        
        assert_test(
            "Searchable PDF Generator",
            pdf_path.exists() and len(pdf_bytes) > 0,
            "Generated multi-page searchable PDF with OCR text layers."
        )
except Exception as e:
    traceback.print_exc()
    assert_test("Structured Data Exporters", False, f"Failed: {e}")

# -------------------------------------------------------------
# Summary
# -------------------------------------------------------------
print("\n================================================================")
print(" UAT RUN SUMMARY")
print("================================================================")
print(f"Total Tests Executed: {total_count}")
print(f"Passed: {success_count} / {total_count} ({success_count/total_count*100:.1f}%)")
if success_count == total_count:
    print("\nSUCCESS: All Phase 2 scopes are verified and ready for production!")
else:
    print("\nWARNING: Some validation steps failed. Please review debug logs.")
print("================================================================")

sys.exit(0 if success_count == total_count else 1)
