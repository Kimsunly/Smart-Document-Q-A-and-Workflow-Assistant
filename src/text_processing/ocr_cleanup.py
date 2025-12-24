# src/text_processing/ocr_cleanup.py
import re


def clean_ocr_text(text: str) -> str:
    """
    Improved OCR cleanup:
    - Remove non-printable characters
    - Normalize spaces, punctuation, quotes, dashes
    - Remove obvious OCR noise
    - Preserve line breaks for readability
    """

    # Remove non-printable characters
    text = ''.join(c if c.isprintable() else ' ' for c in text)

    # Normalize common OCR punctuation issues
    replacements = {
        "“": '"', "”": '"',
        "‘": "'", "’": "'",
        "–": "-", "—": "-",
        "…": "...",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)

    # Fix spacing around punctuation
    text = re.sub(r'\s+([,.;:!?])', r'\1', text)  # "Hello ." -> "Hello."
    # "Hello.World" -> "Hello. World"
    text = re.sub(r'([,.;:!?])([A-Za-z])', r'\1 \2', text)

    # Remove ASCII noise
    text = re.sub(r'[|]{2,}', '', text)   # remove ||| noise
    text = re.sub(r'[_]{3,}', '', text)   # remove ___ noise
    text = re.sub(r'[-]{5,}', '', text)   # remove -----

    # Collapse excessive spaces but KEEP newlines
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # Normalize multiple newlines to two (paragraph spacing)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Strip whitespace on each line
    clean_lines = []
    for line in text.split("\n"):
        stripped = line.strip()

        # Skip garbage OCR lines (1–2 random characters)
        if len(stripped) <= 2 and not stripped.isdigit():
            continue

        clean_lines.append(stripped)

    return "\n".join(clean_lines).strip()
