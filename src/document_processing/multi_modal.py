import base64
import os
import re
import json
import urllib.request
import urllib.error
from typing import List, Dict, Any, Tuple
import fitz  # PyMuPDF
from common.logger import document_logger

def extract_pdf_images(pdf_path: str) -> List[Tuple[int, bytes]]:
    """
    Extract images from PDF pages.
    Filters out small icons, logos, and low-res graphics.
    Returns: List of (page_number, image_bytes)
    """
    images = []
    try:
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc, start=1):
            image_list = page.get_images(full=True)
            for img_info in image_list:
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image.get("image")
                if not image_bytes:
                    continue
                
                # Filter out small icons/decorations
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)
                if width < 150 or height < 150 or len(image_bytes) < 12000:
                    continue
                
                images.append((page_num, image_bytes))
        doc.close()
    except Exception as e:
        document_logger.error(f"Error extracting images from PDF {pdf_path}: {e}")
    return images

def describe_image_via_vision(image_bytes: bytes, page_num: int, model: str = "moondream") -> str:
    """
    Send base64-encoded image to Ollama vision API for description.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    url = f"{base_url}/api/generate"
    
    # Base64 encode the image
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    
    prompt = (
        "This is an image, diagram, table, or chart extracted from page {} of a document. "
        "Please describe it in comprehensive detail. "
        "If it is a network topology diagram, list all devices (such as routers, switches, servers, hosts) "
        "and specify how they are connected. "
        "If it is a table or chart, explain all rows, columns, and data values. "
        "Do not include any conversational introduction, output ONLY the detailed description."
    ).format(page_num)
    
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [b64_image],
        "stream": False
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        # Use a 30-second timeout for local vision inference
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            return (parsed.get("response") or "").strip()
    except Exception as e:
        document_logger.warning(f"Ollama vision model call failed (check if '{model}' is pulled): {e}")
        return ""

def process_pdf_multimodal(pdf_path: str, doc_id: str, model: str = "moondream") -> List[Dict[str, Any]]:
    """
    Extract images, describe them, and return them as searchable document chunks.
    """
    chunks = []
    images = extract_pdf_images(pdf_path)
    if not images:
        return []
        
    document_logger.info(f"Extracted {len(images)} potential diagrams/tables from PDF {pdf_path}. Describing them...")
    
    for idx, (page_num, image_bytes) in enumerate(images):
        description = describe_image_via_vision(image_bytes, page_num, model=model)
        if description:
            chunk_text = f"[Embedded Diagram / Table on Page {page_num}]:\n{description}"
            chunks.append({
                "doc_id": doc_id,
                "page": page_num,
                "chunk_id": f"{doc_id}_page{page_num}_img{idx}",
                "text": chunk_text,
                "source_type": "diagram"
            })
            
    return chunks
