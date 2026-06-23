#!/usr/bin/env python
"""Wrapper script to run test_router with proper path setup"""
from document_processing.test_router import test_pdf_classification
import sys
import os
from pathlib import Path

# Set working directory to script location
script_dir = Path(__file__).parent
os.chdir(script_dir)

# Add src to path BEFORE any imports
src_path = script_dir / "src"
sys.path.insert(0, str(src_path))

print(f"Script dir: {script_dir}")
print(f"Src path: {src_path}")
print(f"Adding to sys.path: {str(src_path)}")

# Now import and run

if __name__ == "__main__":
    test_pdf_classification()
