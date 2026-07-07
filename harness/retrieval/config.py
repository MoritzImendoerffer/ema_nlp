"""Declarative retrieval-pipeline config (config-driven, not hardcoded).

Loaded from ``harness/configs/retrieval/<profile>.yaml``. Kept separate from the
existing ``harness/configs/index/*.yaml`` index profiles so it neither disturbs
the live index loader nor drags Neo4j imports. ``resolved_attributes`` reuses the
transparency helper so the *active* pipeline is stamped on every trace.

See ``docs/TARGET_ARCHITECTURE.md`` §4.4 / §4.7.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness.obs import resolved_config_attributes

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "configs" / "retrieval"


@dataclass
class RetrievalPipelineConfig:
    """Resolved retrieval pipeline: query transform -> rerank.

    Holds exactly the stages ``assemble_agent`` wires — no more. The former
    ``sub_retrievers``/``graph_mode``/``k`` fields were declared-but-unconsumed
    (F8) and were removed 2026-07-05; native sub-retriever composition remains an
    *object-level* seam (``native_pg.py``) until a config surface is actually
    needed. Retrieval ``k`` lives in the index profile (the one live ``k``).
    """

    profile: str
    query_transform: str = "none"
    rerank: list[str] = field(default_factory=list)
    rerank_top_n: int = 8
    # Category order for the ``doc_type_priority`` postprocessor (only meaningful
    # when that name appears in ``rerank``); empty = the postprocessor's default.
    doc_type_priority: list[str] = field(default_factory=list)

    def resolved_attributes(self) -> dict[str, Any]:
        """Flatten the *active* pipeline stages to ``ema.retrieval.*`` (honest stamping)."""
        retrieval: dict[str, Any] = {
            "profile": self.profile,
            "query_transform": self.query_transform,
            "rerank": self.rerank,
        }
        if "doc_type_priority" in self.rerank and self.doc_type_priority:
            retrieval["doc_type_priority"] = self.doc_type_priority
        return resolved_config_attributes({"retrieval": retrieval})


def load_pipeline_config(profile: str, *, config_dir: Path | None = None) -> RetrievalPipelineConfig:
    """Load ``harness/configs/retrieval/<profile>.yaml`` into a config object."""
    directory = config_dir or CONFIG_DIR
    path = directory / f"{profile}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Retrieval pipeline config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    section = raw.get("retrieval", raw)
    doc_type_priority = [str(c) for c in (section.get("doc_type_priority") or [])]
    if doc_type_priority:
        from harness.retrieval.doc_categories import CATEGORIES

        unknown = [c for c in doc_type_priority if c not in CATEGORIES]
        if unknown:
            raise ValueError(
                f"retrieval.doc_type_priority has unknown categor(ies) {unknown}; "
                f"valid: {list(CATEGORIES)}"
            )
    return RetrievalPipelineConfig(
        profile=profile,
        query_transform=section.get("query_transform", "none"),
        rerank=list(section.get("rerank", [])),
        rerank_top_n=int(section.get("rerank_top_n", 8)),
        doc_type_priority=doc_type_priority,
    )
