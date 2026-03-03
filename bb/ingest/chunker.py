"""Split long text into overlapping chunks for embedding."""

from __future__ import annotations

MAX_CHARS = 1500
OVERLAP_CHARS = 150


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """
    Split text into chunks at paragraph or sentence boundaries.
    Short texts (< max_chars) are returned as-is.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    # Try splitting on double newlines (paragraphs) first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                # Para itself is too long — split on sentences
                for sentence_chunk in _split_sentences(para, max_chars, overlap):
                    chunks.append(sentence_chunk)
                current = ""

    if current:
        chunks.append(current)

    return chunks


def _split_sentences(text: str, max_chars: int, overlap: int) -> list[str]:
    """Fallback: split on '. ' boundaries with overlap."""
    sentences = text.replace(". ", ".\n").split("\n")
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = f"{current} {s}".strip()
        else:
            if current:
                chunks.append(current)
            # Carry overlap from previous chunk
            tail = current[-overlap:] if len(current) > overlap else current
            current = f"{tail} {s}".strip() if tail else s
    if current:
        chunks.append(current)
    return chunks
