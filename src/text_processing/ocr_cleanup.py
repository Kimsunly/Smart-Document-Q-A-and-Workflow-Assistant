
import re

def clean_ocr_text(text: str) -> str:
    """
    Improved OCR cleanup:
    - Remove non-printable characters
    - Normalize punctuation/quotes/dashes
    - Remove obvious OCR noise
    - Preserve line breaks for readability
    """
    text = ''.join(c if c.isprintable() else ' ' for c in text)

    replacements = {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "..."}
    for bad, good in replacements.items():
        text = text.replace(bad, good)

    text = re.sub(r'\s+([,.;:!?])', r'\1', text)
    text = re.sub(r'([,.;:!?])([A-Za-z])', r'\1 \2', text)

    text = re.sub(r'[|]{2,}', '', text)
    text = re.sub(r'[_]{3,}', '', text)
    text = re.sub(r'[-]{5,}', '', text)

    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    clean_lines = []
    for line in text.split("\n"):
        s = line.strip()
        if len(s) <= 2 and not s.isdigit():
            continue
        clean_lines.append(s)

    return "\n".join(clean_lines).strip()
