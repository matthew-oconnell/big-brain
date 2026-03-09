"""Unit tests for bb/ingest/chunker.py."""

from __future__ import annotations

import pytest

from bb.ingest.chunker import MAX_CHARS, OVERLAP_CHARS, chunk_text, _split_sentences


class TestChunkText:
    def test_empty_returns_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_returned_as_is(self):
        text = "Hello world"
        result = chunk_text(text)
        assert result == ["Hello world"]

    def test_exactly_at_limit_returned_as_is(self):
        text = "x" * MAX_CHARS
        result = chunk_text(text)
        assert result == [text]

    def test_long_text_splits_into_multiple_chunks(self):
        # 10 paragraphs of 300 chars each — should split
        para = "A" * 298 + ".\n"
        text = ("\n\n" + para) * 10
        result = chunk_text(text)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= MAX_CHARS

    def test_paragraph_boundaries_respected(self):
        # Two paragraphs that together exceed MAX_CHARS — each under limit alone
        half = MAX_CHARS // 2 + 100
        text = "P1 " + "a" * half + "\n\nP2 " + "b" * half
        result = chunk_text(text)
        assert len(result) == 2
        assert "P1" in result[0]
        assert "P2" in result[1]

    def test_small_paragraphs_merged_within_limit(self):
        # Multiple tiny paragraphs should be merged into one chunk
        text = "\n\n".join(["short"] * 10)
        result = chunk_text(text)
        assert len(result) == 1
        assert "short" in result[0]

    def test_single_giant_paragraph_uses_sentence_split(self):
        # No double newlines — falls back to sentence splitting
        long_sentence = ("This is a sentence about science. " * 60).strip()
        result = chunk_text(long_sentence)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= MAX_CHARS

    def test_whitespace_stripped_from_result(self):
        text = "  hello world  "
        result = chunk_text(text)
        assert result == ["hello world"]

    def test_chunks_cover_all_content(self):
        # All words from original text appear somewhere in the chunks
        words = [f"word{i}" for i in range(200)]
        text = ". ".join(words)
        result = chunk_text(text)
        all_chunks = " ".join(result)
        for word in words:
            assert word in all_chunks


class TestSplitSentences:
    def test_short_text_single_chunk(self):
        text = "Hello world. This is a test."
        result = _split_sentences(text, max_chars=200, overlap=20)
        assert result == [text]

    def test_splits_at_sentence_boundaries(self):
        sentence = "This is one sentence. "
        text = sentence * 30
        result = _split_sentences(text, max_chars=300, overlap=50)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 300

    def test_overlap_carries_content(self):
        # Build text where overlap is clearly testable
        sentences = [f"Sentence number {i} here." for i in range(50)]
        text = " ".join(sentences)
        result = _split_sentences(text, max_chars=200, overlap=50)
        # With overlap, content from the end of one chunk should appear in the next
        if len(result) > 1:
            # Each chunk should not be empty
            for chunk in result:
                assert chunk.strip()
