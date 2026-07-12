"""Pure source-category steering primitives (no LLM, no store, offline-testable).

Steering never hardcodes a category or topic: everything operates on the generic
category vocabulary from :mod:`harness.retrieval.doc_categories` plus values that
arrive from config (index profile / routing table) or from the agent's tool call.

Three consumers:
  - ``HierarchicalPGRetriever`` — quota stratification over the oversampled pool
    (:func:`stratify_by_category`).
  - the ``ema_search`` tool — per-call category parsing
    (:func:`parse_categories`) and routing-prior reordering
    (:func:`sort_by_category_priority`).
  - ``DocTypePriorityPostprocessor`` — delegates its ordering here so the sort
    logic exists once.

See ``docs/RETRIEVAL.md`` ("Steering retrieval by source category").
"""

from __future__ import annotations

from typing import Any

from harness.retrieval.doc_categories import CATEGORIES, classify_source


def node_category(node_with_score: Any) -> str:
    """Category of a retrieved node: stamped metadata first, else classified.

    Works on ``NodeWithScore`` or bare nodes; returns ``"other"`` when nothing
    is known — never raises.
    """
    node = getattr(node_with_score, "node", node_with_score)
    meta = getattr(node, "metadata", {}) or {}
    return meta.get("category") or classify_source(
        meta.get("source_url") or "", meta.get("topic_path") or ""
    )


def parse_categories(raw: str) -> list[str]:
    """Parse a comma-separated category string into validated category names.

    Raises ``ValueError`` (with the valid vocabulary in the message, so an agent
    seeing the error can self-correct) on unknown names; returns ``[]`` for an
    empty/whitespace input.
    """
    cats = [c.strip() for c in (raw or "").split(",") if c.strip()]
    unknown = [c for c in cats if c not in CATEGORIES]
    if unknown:
        raise ValueError(
            f"Unknown source categor(ies) {unknown}. Valid categories: {list(CATEGORIES)}"
        )
    return cats


def sort_by_category_priority(nodes: list, priority: list[str]) -> list:
    """Stable-sort nodes so categories earlier in ``priority`` come first.

    Ties (same category, and every category not in ``priority``) keep their
    original — i.e. score — order. This is the shared ordering behind both the
    ``doc_type_priority`` postprocessor and routing's ``prefer`` mode.
    """
    order = {category: i for i, category in enumerate(priority)}

    def sort_key(indexed: tuple[int, Any]) -> tuple[int, int]:
        i, nws = indexed
        return (order.get(node_category(nws), len(order)), i)

    return [n for _, n in sorted(enumerate(nodes), key=sort_key)]


def stratify_by_category(nodes: list, quotas: dict[str, int], k: int) -> list:
    """Pick ``k`` nodes from a (score-ordered) pool with per-category guarantees.

    ``quotas`` maps category -> minimum slots reserved for that category, e.g.
    ``{"scientific_guideline": 2}`` guarantees the two best guideline hits in the
    pool make the cut even if ``k`` higher-scoring nodes of other categories
    exist. Quotas are guarantees, not requirements: a category with fewer pool
    members than its quota just yields what it has, and freed slots go to the
    best remaining nodes. The result preserves the pool's original (score)
    order — stratification changes *membership*, never ranking.
    """
    if k <= 0:
        return []
    if not quotas or len(nodes) <= k:
        return nodes[:k]
    rank = {id(n): i for i, n in enumerate(nodes)}
    chosen_ids: set[int] = set()
    chosen: list = []

    def take(n: Any) -> None:
        if id(n) not in chosen_ids and len(chosen) < k:
            chosen_ids.add(id(n))
            chosen.append(n)

    for category, quota in quotas.items():
        for n in [n for n in nodes if node_category(n) == category][: max(int(quota), 0)]:
            take(n)
    for n in nodes:
        if len(chosen) >= k:
            break
        take(n)
    return sorted(chosen, key=lambda n: rank[id(n)])


def validate_quota(quotas: dict[str, int], *, k: int | None = None) -> None:
    """Validate a category-quota mapping (config-load-time, fail loudly).

    Unknown categories, non-positive quotas, or a quota total exceeding ``k``
    (the guarantees could never all be honoured) are hard config errors.
    """
    unknown = [c for c in quotas if c not in CATEGORIES]
    if unknown:
        raise ValueError(
            f"category_quota has unknown categor(ies) {unknown}; valid: {list(CATEGORIES)}"
        )
    bad = {c: n for c, n in quotas.items() if int(n) <= 0}
    if bad:
        raise ValueError(f"category_quota values must be >= 1, got {bad}")
    if k is not None and sum(int(n) for n in quotas.values()) > k:
        raise ValueError(
            f"category_quota total ({sum(quotas.values())}) exceeds retrieval k ({k})"
        )
