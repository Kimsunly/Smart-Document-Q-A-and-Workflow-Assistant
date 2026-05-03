import re
import textwrap
from typing import List


def _looks_like_log_block(text: str) -> bool:
    """Detect log/packet dump lines that shouldn't be aggressively merged/wrapped."""
    s = (text or "").lower()
    # heuristics: many numeric tokens, 'reply', 'bytes', 'ttl', 'icmp', 'seq', 'packet'
    num_tokens = len(re.findall(r"\d+", s))
    keywords = sum(1 for k in ("reply", "bytes", "ttl", "icmp",
                   "seq", "packet", "bytes,") if k in s)
    return (num_tokens >= 5) or (keywords >= 1)


def _is_garbage_line(line: str) -> bool:
    if not line:
        return True
    letters = len(re.findall(r"[A-Za-z]", line))
    ratio = letters / max(len(line), 1)
    # If line is mostly punctuation/numbers, mark as garbage-like
    return ratio < 0.35


def _split_paragraphs(text: str) -> List[str]:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # remove hyphen-newline splits but keep intent
    text = re.sub(r"-\n(?=\w)", "", text)
    blocks = re.split(r"\n{2,}", text)
    out = []

    for blk in blocks:
        # preserve left-side spacing
        lines = [ln.rstrip() for ln in blk.split("\n")]
        if not any(l.strip() for l in lines):
            continue

        # conservative merging: join lines that appear to be sentence continuations
        merged_lines = []
        buf = None
        for i, line in enumerate(lines):
            s = line.strip()
            if not s:
                continue

            # if buffer empty, start
            if buf is None:
                buf = s
                continue

            prev = buf
            # If previous ends with sentence punctuation -> start new
            if re.search(r"[\.\?!:;\)]$", prev):
                merged_lines.append(prev)
                buf = s
                continue

            # If current line looks like a heading/bullet -> break
            if re.match(r"^(\d+\.|\d+\)|-\s|\*\s|•\s)", s):
                merged_lines.append(prev)
                buf = s
                continue

            # If prev or current look like log/packet dump, keep separate lines
            if _looks_like_log_block(prev) or _looks_like_log_block(s) or _is_garbage_line(prev) or _is_garbage_line(s):
                merged_lines.append(prev)
                buf = s
                continue

            # Otherwise join as continuation
            buf = prev + " " + s

        if buf:
            merged_lines.append(buf)

        # cleanup extra whitespace
        merged_lines = [re.sub(r"\s+", " ", m).strip()
                        for m in merged_lines if m.strip()]
        if merged_lines:
            out.extend(merged_lines)

    return out


def format_document_text(text: str, width: int = 90, mode: str = "conservative") -> str:
    """
    Format OCR/PDF text for preview.
    Modes:
      - conservative: preserve structure, only join sentence continuations
      - aggressive: merge paragraphs and wrap aggressively (legacy behavior)
    """
    paragraphs = _split_paragraphs(text)
    formatted = []

    for paragraph in paragraphs:
        # If looks like a log/packet block, preserve line breaks and don't wrap aggressively
        if _looks_like_log_block(paragraph):
            # show as-is but wrap long lines mildly
            for line in paragraph.split("\n"):
                formatted.append(textwrap.fill(line, width=width))
            formatted.append("")
            continue

        if mode == "aggressive":
            # aggressive: combine lines into paragraph and wrap
            p = re.sub(r"\s+", " ", paragraph).strip()
            formatted.append(textwrap.fill(p, width=width))
            continue

        # conservative formatting
        # numbered items
        if re.match(r"^\d+[.)]\s+", paragraph):
            heading, rest = paragraph.split(" ", 1)
            formatted.append(heading)
            formatted.append(textwrap.fill(
                rest, width=width, subsequent_indent="  "))
            formatted.append("")
            continue

        # bullets
        if paragraph.startswith(("- ", "* ", "• ")):
            formatted.append(textwrap.fill(
                paragraph, width=width, subsequent_indent="  "))
            formatted.append("")
            continue

        # short label-like lines
        if len(paragraph) <= 80 and (paragraph.endswith(":") or paragraph.isupper() or re.match(r"^[A-Z][A-Za-z0-9\s\-/&]+$", paragraph)):
            formatted.append(paragraph)
            formatted.append("")
            continue

        # default: gentle wrap preserving sentence boundaries
        formatted.append(textwrap.fill(paragraph, width=width))
        formatted.append("")

    # strip trailing empty
    out = "\n".join([p for p in formatted]).strip()
    # clean up double newlines
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out
