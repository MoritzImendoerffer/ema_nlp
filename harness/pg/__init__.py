"""Postgres + pgvector adaptor for the narrative-corpus retrieval path.

Mirrors the public shape of harness/embed.py + harness/retrieve.py so the
workflows can swap retrieval backends via the EMA_RETRIEVER env var without
seeing either store directly.

Subpackage layout:
    conn     — lazy psycopg_pool + pgvector type registration
    queries  — parameterised SQL string constants (no logic)
    adapter  — RetrievalResult <-> LlamaIndex NodeWithScore + get_node_by_id
    tools    — follow_links FunctionTool for ReAct workflows
"""

from harness.pg.conn import close_pool, get_pool

__all__ = ["close_pool", "get_pool"]
