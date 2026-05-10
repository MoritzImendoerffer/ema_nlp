"""Shared data model for Q&A corpus records."""

from __future__ import annotations

import dataclasses
import json
from typing import Literal


@dataclasses.dataclass
class QARecord:
    qa_id: str
    question: str
    answer: str
    source_url: str
    source_type: Literal["html_accordion", "pdf"]
    source_title: str
    topic_path: str
    cross_refs: list[str]
    extraction_confidence: Literal["high", "medium", "low"]
    reference_number: str = ""
    revision: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
