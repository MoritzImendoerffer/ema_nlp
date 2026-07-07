"""ExportBundle — everything one turn's export (or external review tool) needs.

Built by ``app.py`` at the end of a turn and held in the session
(``cl.user_session["turn_bundles"]``). ``to_dict()`` is the **tool-neutral
interchange format**: the Markdown/HTML exporters, the SME review element's
props, and — if review volume ever outgrows the chat — a dedicated annotation
tool (e.g. a Label Studio task) all consume this same JSON shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.attribution import Attribution
from harness.schemas import RegulatoryAnswer


@dataclass
class ExportBundle:
    """One answered turn: query, config, answer, attribution, references, scores."""

    question: str
    answer: RegulatoryAnswer
    attribution: Attribution
    recipe_name: str = ""
    resolved_config: dict[str, Any] = field(default_factory=dict)  # ema.* attributes
    settings: dict[str, Any] = field(default_factory=dict)  # live panel overrides
    judge_results: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    run_id: str = ""
    trace_id: str = ""
    trace_url: str = ""
    msg_num: int = 0
    asked_at: str = ""  # ISO timestamp, stamped by the caller

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer.model_dump(),
            "attribution": self.attribution.to_dict(),
            "recipe_name": self.recipe_name,
            "resolved_config": dict(self.resolved_config),
            "settings": dict(self.settings),
            "judge_results": list(self.judge_results),
            "confidence": self.confidence,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "trace_url": self.trace_url,
            "msg_num": self.msg_num,
            "asked_at": self.asked_at,
        }
