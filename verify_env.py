
import os

def check_streamlit():
    try:
        import streamlit as st
        print("[OK] streamlit imported")
        try:
            from importlib.metadata import version
            ver = version("streamlit")
        except Exception:
            ver = "unknown"
        print("    streamlit version:", ver)
    except Exception as e:
        print("[ERROR] streamlit:", e)

def check_opencv():
    try:
        import cv2
        print("[OK] OpenCV imported")
        print("    cv2 version:", cv2.__version__)
    except Exception as e:
        print("[ERROR] OpenCV:", e)

def check_tesseract():
    try:
        import pytesseract
        print("[OK] pytesseract imported")
        print("    tesseract_cmd:", pytesseract.pytesseract.tesseract_cmd)
        try:
            print("    version:", pytesseract.get_tesseract_version())
        except Exception:
            pass
    except Exception as e:
        print("[ERROR] pytesseract:", e)

def check_pdf2image():
    try:
        from pdf2image import convert_from_bytes
        print("[OK] pdf2image imported")
        path_env = os.environ.get("PATH", "")
        print("    PATH contains poppler:", "poppler" in path_env.lower())
    except Exception as e:
        print("[ERROR] pdf2image:", e)

def check_docx():
    try:
        import docx
        print("[OK] python-docx imported")
    except Exception as e:
        print("[ERROR] python-docx:", e)

def check_paddle():
    try:
        import paddle
        import paddleocr
        print("[OK] Paddle and PaddleOCR imported")
        print("    paddle version:", paddle.__version__)
    except Exception as e:
        print("[ERROR] Paddle/PaddleOCR:", e)

if __name__ == "__main__":
    check_streamlit()
    check_opencv()
    check_tesseract()
    check_pdf2image()
    check_docx()
    check_paddle()
