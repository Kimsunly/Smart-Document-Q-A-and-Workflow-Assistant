import re

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)  # remove extra spaces/newlines
    return text.strip()
