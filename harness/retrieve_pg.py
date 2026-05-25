"""Retrieval façade for the Postgres + pgvector narrative corpus.

This module mirrors the public surface of ``harness/retrieve.py``:

    RetrievalConfigPG          — drop-in replacement for RetrievalConfig
    PrefilterConfig            — SQL-level pre-filter (committee, topic, date)
    TraversalConfig            — link-graph traversal mode + bounds
    RetrievalResult            — same shape as harness.retrieve.RetrievalResult
    retrieve_with_config_pg    — single entry point (filled in by NARR-016+)
    build_retrieve_fn_pg       — factory for the workflow callable (NARR-018)

NARR-015 lands the scaffolding (config dataclasses + YAML round-trip). The
actual dense / BM25 / hybrid / traversal implementations arrive in
NARR-016 → NARR-019. ``retrieve_with_config_pg`` raises ``NotImplementedError``
for now so callers fail loudly until those tasks complete.

YAML shape (extension of the existing ``retrieval:`` block)::

    retrieval:
      mode: hybrid                  # dense | bm25 | hybrid
      k: 10
      prefilter:
        topic_path_prefix: "/en/medicines/"
        committee: ["CHMP", "PRAC"]
        date_range: ["2020-01-01", "2024-12-31"]
      traversal:
        mode: auto                  # none | auto | agent_tool
        max_hops: 1
        link_types: ["hyperlink", "reference_number"]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

# (chunk_id, score, metadata) — same tuple shape as harness.retrieve.RetrievalResult
# so workflow code that already consumes RetrievalResult can read either path.
RetrievalResult = tuple[str, float, dict[str, Any]]

RetrieverMode = Literal["dense", "bm25", "hybrid"]
TraversalMode = Literal["none", "auto", "agent_tool"]

# Link types that may appear in the ``links`` table; matches link_extractor.LinkType.
LinkType = Literal["hyperlink", "reference_number", "see_qa"]
_DEFAULT_LINK_TYPES: tuple[str, ...] = ("hyperlink", "reference_number")


def _parse_date(value: Any) -> datetime | None:
    """Parse ISO date or datetime string; return tz-aware datetime (UTC) or None.

    Accepts ``datetime`` and ``date`` instances unchanged (date promoted to UTC
    midnight). Strings are parsed via ``datetime.fromisoformat`` with a Z-suffix
    fallback. None / empty returns None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Allow plain YYYY-MM-DD
            try:
                dt = datetime.strptime(s, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"unparseable date: {value!r}") from exc
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    raise TypeError(f"unsupported date type: {type(value).__name__}")


@dataclass
class PrefilterConfig:
    """SQL ``WHERE`` clauses applied before the ANN / BM25 ranking.

    Empty defaults disable each filter. Concrete SQL composition is the job
    of the retrievers in NARR-016 / NARR-017.
    """
    topic_path_prefix: str | None = None
    committee: list[str] = field(default_factory=list)
    date_range: tuple[datetime, datetime] | None = None

    @classmethod
    def from_dict(cls, cfg: dict[str, Any] | None) -> PrefilterConfig:
        if not cfg:
            return cls()
        dr_raw = cfg.get("date_range")
        date_range: tuple[datetime, datetime] | None = None
        if dr_raw:
            if not isinstance(dr_raw, (list, tuple)) or len(dr_raw) != 2:
                raise ValueError("prefilter.date_range must be a [start, end] pair")
            start = _parse_date(dr_raw[0])
            end = _parse_date(dr_raw[1])
            if start is None or end is None:
                raise ValueError("prefilter.date_range start/end must both be set")
            if start > end:
                raise ValueError("prefilter.date_range start must be <= end")
            date_range = (start, end)
        committee_raw = cfg.get("committee") or []
        if isinstance(committee_raw, str):
            committee_raw = [committee_raw]
        committee = [str(c).strip() for c in committee_raw if str(c).strip()]
        topic = cfg.get("topic_path_prefix") or None
        return cls(
            topic_path_prefix=str(topic) if topic else None,
            committee=committee,
            date_range=date_range,
        )

    @property
    def is_empty(self) -> bool:
        return not (self.topic_path_prefix or self.committee or self.date_range)


@dataclass
class TraversalConfig:
    """Configure the post-retrieval link-graph expansion."""
    mode: TraversalMode = "none"
    max_hops: int = 1
    link_types: list[str] = field(default_factory=lambda: list(_DEFAULT_LINK_TYPES))

    @classmethod
    def from_dict(cls, cfg: dict[str, Any] | None) -> TraversalConfig:
        if not cfg:
            return cls()
        mode = cfg.get("mode", "none")
        if mode not in ("none", "auto", "agent_tool"):
            raise ValueError(f"traversal.mode must be none|auto|agent_tool, got {mode!r}")
        max_hops = int(cfg.get("max_hops", 1))
        if max_hops < 0:
            raise ValueError("traversal.max_hops must be >= 0")
        link_types_raw = cfg.get("link_types") or list(_DEFAULT_LINK_TYPES)
        if isinstance(link_types_raw, str):
            link_types_raw = [link_types_raw]
        link_types = [str(lt).strip() for lt in link_types_raw if str(lt).strip()]
        return cls(mode=mode, max_hops=max_hops, link_types=link_types)


@dataclass
class RetrievalConfigPG:
    """Unified retrieval config for the pgvector path.

    Workflows (and run_eval YAML) treat this as the public surface; the dense /
    BM25 / hybrid implementations choose how to honour each field.
    """
    mode: RetrieverMode = "hybrid"
    k: int = 10
    prefilter: PrefilterConfig = field(default_factory=PrefilterConfig)
    traversal: TraversalConfig = field(default_factory=TraversalConfig)

    @classmethod
    def from_yaml_section(cls, cfg: dict[str, Any] | None) -> RetrievalConfigPG:
        cfg = cfg or {}
        mode = cfg.get("mode", "hybrid")
        if mode not in ("dense", "bm25", "hybrid"):
            raise ValueError(f"retrieval.mode must be dense|bm25|hybrid, got {mode!r}")
        k = int(cfg.get("k", 10))
        if k <= 0:
            raise ValueError("retrieval.k must be > 0")
        prefilter = PrefilterConfig.from_dict(cfg.get("prefilter"))
        traversal = TraversalConfig.from_dict(cfg.get("traversal"))
        return cls(mode=mode, k=k, prefilter=prefilter, traversal=traversal)


def retrieve_with_config_pg(
    config: RetrievalConfigPG,
    query: str,
    *,
    embed_model: Any = None,
) -> list[RetrievalResult]:
    """Single entry point for pgvector retrieval — filled in by NARR-016..019.

    NARR-015 ships only the config scaffolding so YAML configs can already
    declare a ``retrieval:`` block targeting the pg backend. Callers that
    invoke this function before NARR-018 lands get a clear NotImplementedError.
    """
    raise NotImplementedError(
        "retrieve_with_config_pg arrives in NARR-016..018 (dense, bm25, hybrid)."
    )


def build_retrieve_fn_pg(config: RetrievalConfigPG, **_kwargs: Any):
    """Return a ``fn(query) -> list[RetrievalResult]`` matching harness.retrieve.

    Implementation lands in NARR-018; the stub keeps the import surface stable
    so app.py / run_eval.py can be wired in NARR-021/-022 before the function
    body exists.
    """
    raise NotImplementedError(
        "build_retrieve_fn_pg arrives in NARR-018 (hybrid + dispatcher)."
    )
