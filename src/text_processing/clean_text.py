import re

def clean_text(text: str) -> str:
    """
    Clean whitespace and normalize text, preserving paragraph and line structures.
    """
    if not text:
        return ""
    # Normalize tabs/multiple spaces to single spaces
    text = re.sub(r'[ \t]+', ' ', text)
    # Normalize excessive newlines to double newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip whitespace from individual lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    # Re-normalize excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
