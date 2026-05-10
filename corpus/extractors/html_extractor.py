"""
HTML accordion extractor for EMA Q&A pages.

EMA Q&A pages use Bootstrap accordion components:
  <div class="accordion">
    <div class="accordion-item">
      <h2 class="accordion-header">
        <button class="accordion-button">Question heading</button>
      </h2>
      <div class="accordion-collapse">
        <div class="accordion-body">Answer text...</div>
      </div>
    </div>
  </div>

The outer <div class="accordion"> is a section wrapper (one per topic section).
The inner <div class="accordion-item"> elements are individual Q/A pairs.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from corpus.models import QARecord

# Question-form signals (any match → high confidence)
_QUESTION_RE = re.compile(
    r"^(what|when|where|which|who|why|how|should|can|could|does|do|is|are|may|"
    r"will|must|has|have|would|shall|need|did|was|were|am|does)\b",
    re.IGNORECASE,
)


def _qa_id(source_url: str, question: str) -> str:
    """Stable 16-char hex id: sha256(url + NUL + normalised question)."""
    normalised = " ".join(question.lower().split())
    raw = source_url + "\x00" + normalised
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _topic_path(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p and p != "en"]
    if parts and "." in parts[-1]:
        parts = parts[:-1]
    return "/" + "/".join(parts[:5])


def _get_text(tag: Tag) -> str:
    return tag.get_text(separator=" ", strip=True)


def _confidence(heading: str) -> Literal["high", "medium", "low"]:
    heading_stripped = heading.rstrip("?").strip()
    if heading.endswith("?"):
        return "high"
    if _QUESTION_RE.match(heading_stripped):
        return "high"
    return "medium"


def _source_title(soup: BeautifulSoup) -> str:
    """Extract the page title from <h1> or <title>."""
    h1 = soup.find("h1")
    if h1:
        return _get_text(h1)[:200]
    title = soup.find("title")
    if title:
        return _get_text(title).split("|")[0].strip()[:200]
    return ""


def extract_from_html(html: str, source_url: str) -> list[QARecord]:
    """
    Extract Q&A pairs from EMA HTML accordion page.

    Returns one QARecord per accordion-item. Items with empty heading or
    empty body are skipped. The outer accordion wrapper is the section;
    only accordion-items are individual Q/A pairs.
    """
    soup = BeautifulSoup(html, "lxml")
    topic = _topic_path(source_url)
    title = _source_title(soup)
    records: list[QARecord] = []

    for item in soup.find_all(class_="accordion-item"):
        # --- question ---
        header = item.find(class_="accordion-header")
        if not header:
            continue
        button = header.find("button")
        heading_text = _get_text(button if button else header)
        if not heading_text:
            continue

        # --- answer ---
        body = item.find(class_="accordion-body")
        if not body:
            continue
        answer_text = _get_text(body)
        if not answer_text:
            continue

        records.append(
            QARecord(
                qa_id=_qa_id(source_url, heading_text),
                question=heading_text,
                answer=answer_text,
                source_url=source_url,
                source_type="html_accordion",
                source_title=title,
                topic_path=topic,
                cross_refs=[],
                extraction_confidence=_confidence(heading_text),
            )
        )

    return records


def extract_from_file(path: Path, source_url: str) -> list[QARecord]:
    """Convenience wrapper that reads an HTML file."""
    return extract_from_html(path.read_text(encoding="utf-8"), source_url)
