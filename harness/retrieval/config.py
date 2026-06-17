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
    """Resolved retrieval pipeline: transform -> sub-retrievers -> rerank."""

    profile: str
    query_transform: str = "none"
    sub_retrievers: list[str] = field(default_factory=lambda: ["chunk_vector"])
    graph_mode: str = "none"  # none | links | ontology | entity_seeded (explicit)
    k: int = 10
    rerank: list[str] = field(default_factory=list)
    rerank_top_n: int = 8

    def resolved_attributes(self) -> dict[str, Any]:
        """Flatten to ``ema.retrieval.*`` trace attributes (no silent modes)."""
        return resolved_config_attributes(
            {
                "retrieval": {
                    "profile": self.profile,
                    "query_transform": self.query_transform,
                    "sub_retrievers": self.sub_retrievers,
                    "graph_mode": self.graph_mode,
                    "k": self.k,
                    "rerank": self.rerank,
                }
            }
        )


def load_pipeline_config(profile: str, *, config_dir: Path | None = None) -> RetrievalPipelineConfig:
    """Load ``harness/configs/retrieval/<profile>.yaml`` into a config object."""
    directory = config_dir or CONFIG_DIR
    path = directory / f"{profile}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Retrieval pipeline config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    section = raw.get("retrieval", raw)
    return RetrievalPipelineConfig(
        profile=profile,
        query_transform=section.get("query_transform", "none"),
        sub_retrievers=list(section.get("sub_retrievers", ["chunk_vector"])),
        graph_mode=section.get("graph_mode", "none"),
        k=int(section.get("k", 10)),
        rerank=list(section.get("rerank", [])),
        rerank_top_n=int(section.get("rerank_top_n", 8)),
    )
