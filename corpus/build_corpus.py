"""
Source-agnostic corpus builder: dedup → filter → write JSONL.

Entry point: build_corpus(records, output_path) → CorpusStats

The caller supplies an Iterable[QARecord] from any source (MongoDB adaptor,
HTTP fetcher, test fixtures, etc.).  No pymongo import here.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from corpus.models import QARecord

log = logging.getLogger(__name__)


@dataclasses.dataclass
class CorpusStats:
    total_input: int = 0
    deduped: int = 0       # records dropped because a preferred version existed
    filtered: int = 0      # records dropped as landing pages
    total_output: int = 0
    by_source_type: dict[str, int] = dataclasses.field(default_factory=dict)
    by_topic_path: dict[str, int] = dataclasses.field(default_factory=dict)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _dedup_key(record: QARecord) -> str:
    """Stable key for dedup: hash of normalised question text only."""
    return hashlib.sha256(_normalise(record.question).encode()).hexdigest()


def _is_landing_page(record: QARecord) -> bool:
    """
    True if the record looks like a navigation/landing page rather than
    a real Q&A.  Heuristic: low confidence, no cross-refs, short answer.
    """
    return (
        record.extraction_confidence == "low"
        and not record.cross_refs
        and len(record.answer) < 100
    )


def _dedup(records: list[QARecord], dedup_log_path: Path) -> list[QARecord]:
    """
    Remove duplicate questions.  When an HTML and PDF version of the same
    question exist, keep the PDF (richer metadata).  Otherwise keep the
    first-seen record.

    Priority order (higher = preferred):
      pdf > html_accordion
    """
    _PRIORITY = {"pdf": 1, "html_accordion": 0}

    seen: dict[str, QARecord] = {}
    for rec in records:
        key = _dedup_key(rec)
        if key not in seen:
            seen[key] = rec
        else:
            incumbent = seen[key]
            if _PRIORITY.get(rec.source_type, 0) > _PRIORITY.get(incumbent.source_type, 0):
                seen[key] = rec

    kept = list(seen.values())
    dropped = len(records) - len(kept)

    with dedup_log_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            key = _dedup_key(rec)
            if seen[key].qa_id != rec.qa_id:
                fh.write(json.dumps({
                    "dropped_qa_id": rec.qa_id,
                    "kept_qa_id": seen[key].qa_id,
                    "question_preview": rec.question[:80],
                    "reason": "duplicate; preferred source_type kept",
                }) + "\n")

    log.info("Dedup: %d input → %d kept, %d dropped", len(records), len(kept), dropped)
    return kept


def _filter_landing_pages(records: list[QARecord], filter_log_path: Path) -> list[QARecord]:
    kept, dropped_list = [], []
    for rec in records:
        if _is_landing_page(rec):
            dropped_list.append(rec)
        else:
            kept.append(rec)

    with filter_log_path.open("w", encoding="utf-8") as fh:
        for rec in dropped_list:
            fh.write(json.dumps({
                "qa_id": rec.qa_id,
                "source_url": rec.source_url,
                "question_preview": rec.question[:80],
                "reason": "landing-page heuristic (low confidence, no cross_refs, short answer)",
            }) + "\n")

    log.info("Filter: %d input → %d kept, %d landing pages dropped",
             len(records), len(kept), len(dropped_list))
    return kept


def build_corpus(
    records: Iterable[QARecord],
    output_path: Path,
    *,
    dedup_log_path: Path | None = None,
    filter_log_path: Path | None = None,
) -> CorpusStats:
    """
    Dedup, filter, and write records to a JSONL file.

    Args:
        records:          Any iterable of QARecord objects.
        output_path:      Destination .jsonl file (created/overwritten).
        dedup_log_path:   Where to write the dedup log (default: alongside output).
        filter_log_path:  Where to write the filter log (default: alongside output).

    Returns:
        CorpusStats with counts and breakdowns.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if dedup_log_path is None:
        dedup_log_path = output_path.with_name(output_path.stem + "_dedup_log.jsonl")
    if filter_log_path is None:
        filter_log_path = output_path.with_name(output_path.stem + "_filter_log.jsonl")

    all_records = list(records)
    stats = CorpusStats(total_input=len(all_records))

    deduped = _dedup(all_records, Path(dedup_log_path))
    stats.deduped = stats.total_input - len(deduped)

    filtered = _filter_landing_pages(deduped, Path(filter_log_path))
    stats.filtered = len(deduped) - len(filtered)

    stats.total_output = len(filtered)

    by_type: dict[str, int] = defaultdict(int)
    by_topic: dict[str, int] = defaultdict(int)

    with output_path.open("w", encoding="utf-8") as fh:
        for rec in filtered:
            fh.write(rec.to_json() + "\n")
            by_type[rec.source_type] += 1
            by_topic[rec.topic_path] += 1

    stats.by_source_type = dict(by_type)
    stats.by_topic_path = dict(by_topic)

    log.info(
        "Corpus written: %d records → %s  (%d deduped, %d filtered)",
        stats.total_output, output_path, stats.deduped, stats.filtered,
    )
    return stats
