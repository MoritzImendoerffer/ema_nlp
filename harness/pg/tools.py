"""LlamaIndex FunctionTool wrappers over the pgvector layer.

Currently exports one tool: :data:`follow_links_tool`. It walks one hop along
the ``links`` graph from a previously-retrieved chunk and returns up to ``k``
neighbour chunks. Designed for ReAct-style workflows
(``harness/workflows/react_native.py``) when
``TraversalConfig.mode == 'agent_tool'`` — instead of expanding the link
graph automatically inside the retriever, the agent decides when to call this
tool.

The plain Python entry point :func:`follow_links` is also exported so unit
tests / harness code can invoke it directly without going through the tool
abstraction.
"""

from __future__ import annotations

from typing import Any

from llama_index.core.tools import FunctionTool

from harness.pg import queries as Q
from harness.pg.adapter import row_to_result
from harness.pg.conn import get_pool

_DEFAULT_FOLLOW_LINK_TYPES: tuple[str, ...] = ("hyperlink", "reference_number")

_FOLLOW_LINKS_DESCRIPTION = (
    "Given a chunk_id from a previously retrieved chunk, return up to k "
    "neighbour chunks reached by following the source document's outgoing "
    "links. Useful when an answer likely involves documents that are cross-"
    "referenced from one already in the retrieval set — e.g. a guideline "
    "that cites another guideline by reference number or by URL. "
    "Arguments: chunk_id (string, required) — the id of the seed chunk; "
    "link_types (list[str], optional) — which edge kinds to follow, defaults "
    "to ['hyperlink','reference_number']; k (int, optional, default 5) — "
    "maximum neighbours to return. "
    "Returns: list of (chunk_id, score, metadata) tuples; score is 0.0 "
    "(these chunks were reached by graph traversal, not ranking)."
)


def follow_links(
    chunk_id: str,
    link_types: list[str] | None = None,
    k: int = 5,
) -> list[tuple[str, float, dict[str, Any]]]:
    """Walk one hop along the link graph starting at ``chunk_id``'s source doc.

    Returns at most ``k`` representative chunks (one per neighbour document,
    chosen as the chunk with the lowest chunk_index — deterministic). The
    ``score`` field is set to ``0.0`` because these chunks were not ranked
    against any query; the agent should treat them as supporting evidence
    pointers rather than direct top-k matches.

    An unknown or empty ``chunk_id`` returns an empty list rather than raising,
    so the agent loop is robust to model-hallucinated ids.
    """
    if not chunk_id:
        return []
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id FROM chunks WHERE chunk_id = %(chunk_id)s",
                {"chunk_id": chunk_id},
            )
            row = cur.fetchone()
    if row is None:
        return []
    src_doc_id = row[0]
    types = list(link_types) if link_types else list(_DEFAULT_FOLLOW_LINK_TYPES)
    params = {
        "seed_doc_ids": [src_doc_id],
        "max_hops": 1,
        "link_types": types,
    }
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(Q.TRAVERSE_LINKS, params)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
    limit = max(0, int(k))
    return [row_to_result(cols, r) for r in rows[:limit]]


follow_links_tool: FunctionTool = FunctionTool.from_defaults(
    fn=follow_links,
    name="follow_links",
    description=_FOLLOW_LINKS_DESCRIPTION,
)
