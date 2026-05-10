"""
PDF Q&A extractor for EMA Q&A documents.

EMA Q&A PDFs have a consistent structure:
  - Title page with reference number (e.g. "EMA/CHMP/508188/2013")
  - Optional revision history table
  - Numbered Q/A sections as Markdown h2 headings after pymupdf4llm conversion:
      ## **1. What is benzyl alcohol...?**
      Answer text...
      ## **2. Which medicinal products...?**
      ...
  - References section (excluded from Q&A extraction)

Cross-references within the document appear as "see Q&A N" or "see question N".
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from corpus.models import QARecord

# Matches numbered section headings from pymupdf4llm output:
#   ## **1. Question text?**
#   ## 1. Question text?  (without bold)
_HEADING_RE = re.compile(
    r"^#{1,3}\s+(?:\*{1,2})?\s*(\d+)\.\s+(.+?)(?:\*{1,2})?$",
    re.MULTILINE,
)

# Reference number on EMA title pages: EMA/COMMITTEE/NNNN/YYYY or EMA/H/CXXX/...
_REF_NUM_RE = re.compile(
    r"EMA/[A-Z0-9]+/[A-Z0-9/]*/\d{4}(?:\s+Rev\.?\s*\d+)?",
    re.IGNORECASE,
)

# Revision string in revision history tables or headers
_REVISION_RE = re.compile(r"Rev\.?\s*(\d+)", re.IGNORECASE)

# Cross-reference patterns: "see Q&A N", "see question N", "see Q N"
_XREF_RE = re.compile(
    r"[Ss]ee\s+(?:[Qq]&[Aa]|[Qq]uestion|[Qq])\s+(\d+)",
    re.IGNORECASE,
)

# Sections to stop Q&A extraction at
_STOP_SECTIONS = re.compile(
    r"^#{1,3}\s+(?:\*{1,2})?\s*(?:References?|Annex|Appendix|Bibliography)",
    re.IGNORECASE | re.MULTILINE,
)


def _qa_id(source_url: str, question: str) -> str:
    normalised = " ".join(question.lower().split())
    raw = source_url + "\x00" + normalised
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _topic_path(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p and p != "en"]
    if parts and "." in parts[-1]:
        parts = parts[:-1]
    return "/" + "/".join(parts[:5])


def _extract_reference_number(text: str) -> str:
    m = _REF_NUM_RE.search(text[:2000])
    return m.group(0).strip() if m else ""


def _extract_revision(text: str) -> str:
    m = _REVISION_RE.search(text[:2000])
    return f"Rev.{m.group(1)}" if m else ""


def _extract_source_title(text: str) -> str:
    """Find the first h1 heading (title page)."""
    h1 = re.search(r"^# (.+)$", text, re.MULTILINE)
    if h1:
        return h1.group(1).strip().replace("**", "").replace("*", "")[:200]
    return ""


def _cross_refs_for_answer(
    answer_text: str, qa_id_by_seq: dict[int, str]
) -> list[str]:
    """Map 'see Q&A N' references to qa_ids using the sequence map."""
    refs: list[str] = []
    for m in _XREF_RE.finditer(answer_text):
        seq = int(m.group(1))
        if seq in qa_id_by_seq:
            refs.append(qa_id_by_seq[seq])
    return refs


def _split_into_qa(markdown: str) -> list[tuple[int, str, str]]:
    """
    Split markdown into (seq_number, question, answer) tuples.

    Stops at the first non-numbered section (References, Annex, etc.).
    """
    # Truncate at stop sections
    stop = _STOP_SECTIONS.search(markdown)
    if stop:
        markdown = markdown[: stop.start()]

    matches = list(_HEADING_RE.finditer(markdown))
    if not matches:
        return []

    results: list[tuple[int, str, str]] = []
    for i, m in enumerate(matches):
        seq = int(m.group(1))
        question = m.group(2).strip().replace("**", "").replace("*", "").strip()

        # Answer: text between this heading and the next
        answer_start = m.end()
        answer_end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        answer = markdown[answer_start:answer_end].strip()
        # Clean up markdown artefacts: bold markers, page-footer repetitions
        answer = re.sub(r"\*{1,2}", "", answer)
        answer = re.sub(r"\n{3,}", "\n\n", answer).strip()

        if question and answer:
            results.append((seq, question, answer))

    return results


def extract_from_markdown(
    markdown: str, source_url: str, source_title: str = ""
) -> list[QARecord]:
    """
    Extract Q&A pairs from pymupdf4llm markdown output.

    source_title overrides auto-detection when already known.
    """
    if not source_title:
        source_title = _extract_source_title(markdown)
    ref_num = _extract_reference_number(markdown)
    revision = _extract_revision(markdown)
    topic = _topic_path(source_url)

    qa_pairs = _split_into_qa(markdown)
    if not qa_pairs:
        return []

    # Build sequence→qa_id map for cross-reference resolution
    qa_id_by_seq: dict[int, str] = {
        seq: _qa_id(source_url, q) for seq, q, _ in qa_pairs
    }

    records: list[QARecord] = []
    for seq, question, answer in qa_pairs:
        qa_id = qa_id_by_seq[seq]
        refs = _cross_refs_for_answer(answer, qa_id_by_seq)
        # Confidence: high if question ends with ?, medium otherwise
        confidence: Literal["high", "medium", "low"] = "high" if question.endswith("?") else "medium"
        records.append(
            QARecord(
                qa_id=qa_id,
                question=question,
                answer=answer,
                source_url=source_url,
                source_type="pdf",
                source_title=source_title,
                reference_number=ref_num,
                topic_path=topic,
                revision=revision,
                cross_refs=refs,
                extraction_confidence=confidence,
            )
        )
    return records


def extract_from_pdf(
    pdf_path: Path, source_url: str, source_title: str = ""
) -> list[QARecord]:
    """
    Extract Q&A pairs from an EMA Q&A PDF file.

    Flags PDFs with no numbered-heading structure by returning an empty list.
    Callers should log these for manual review.
    """
    try:
        import pymupdf4llm  # local import — optional dep at extraction time
    except ImportError as e:
        raise ImportError("pymupdf4llm required: pip install pymupdf4llm") from e

    markdown = pymupdf4llm.to_markdown(str(pdf_path))
    return extract_from_markdown(markdown, source_url, source_title)
