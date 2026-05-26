"""Unit tests for corpus/ingestion/chunker.py (NARR-004)."""

from __future__ import annotations

from pathlib import Path

import pytest

from corpus.ingestion.chunker import Chunk, ChunkConfig, chunk_markdown

FIXTURES = Path(__file__).parent / "fixtures"
PDF_SAMPLE = (FIXTURES / "ema_pdf_sample.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_default_config_emits_chunks():
    chunks = chunk_markdown(PDF_SAMPLE)
    assert chunks, "expected at least one chunk from the PDF fixture"
    for c in chunks:
        assert isinstance(c, Chunk)
        assert isinstance(c.text, str) and c.text.strip()
        assert isinstance(c.token_count, int) and c.token_count > 0
        assert isinstance(c.chunk_index, int) and c.chunk_index >= 0


def test_chunk_indices_are_dense_and_monotonic():
    chunks = chunk_markdown(PDF_SAMPLE)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_markdown_parser_emits_at_least_two_chunks_with_heading_path():
    """NARR-004 acceptance criterion."""
    chunks = chunk_markdown(PDF_SAMPLE, ChunkConfig(parser="markdown"))
    assert len(chunks) >= 2, f"expected ≥2 chunks, got {len(chunks)}"
    with_heading = [c for c in chunks if c.heading_path]
    assert with_heading, "expected at least one chunk to carry heading_path"


# ---------------------------------------------------------------------------
# Parser switches
# ---------------------------------------------------------------------------


def test_sentence_parser_runs():
    chunks = chunk_markdown(PDF_SAMPLE, ChunkConfig(parser="sentence"))
    assert chunks
    # SentenceSplitter is markdown-blind, so heading_path stays unset.
    assert all(c.heading_path is None for c in chunks)


def test_hierarchical_parser_emits_leaf_chunks():
    chunks = chunk_markdown(
        PDF_SAMPLE,
        ChunkConfig(parser="hierarchical", max_tokens=128, overlap=16),
    )
    assert chunks


# ---------------------------------------------------------------------------
# Sizing / filters
# ---------------------------------------------------------------------------


def test_min_chunk_chars_drops_tiny_sections():
    """A markdown with one tiny section and one large one should drop the tiny."""
    md = "## H1\nshort\n\n## H2\n" + ("This is a longer paragraph. " * 40)
    chunks = chunk_markdown(md, ChunkConfig(parser="markdown", min_chunk_chars=80))
    assert chunks, "expected the long section to survive"
    assert all(len(c.text) >= 80 for c in chunks)


def test_large_section_is_subsplit():
    big = "## Big section\n" + ("This is one sentence. " * 400)
    chunks = chunk_markdown(big, ChunkConfig(parser="markdown", max_tokens=64, overlap=8))
    assert len(chunks) >= 2, "oversized section should split into multiple chunks"
    for c in chunks:
        assert c.heading_path  # heading propagates to sub-splits


def test_empty_input_returns_empty_list():
    assert chunk_markdown("") == []


def test_whitespace_only_input_returns_empty_list():
    assert chunk_markdown("   \n\n   \t   \n") == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_chunk_config_is_frozen():
    cfg = ChunkConfig()
    with pytest.raises((AttributeError, Exception)):
        cfg.parser = "sentence"  # type: ignore[misc]
