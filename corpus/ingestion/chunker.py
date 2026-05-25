"""LlamaIndex-backed chunker with a small dataclass surface.

Public API:
    ChunkConfig            — parser choice + sizing knobs
    Chunk                  — (text, heading_path, token_count, chunk_index)
    chunk_markdown(text, config) -> list[Chunk]

Three parsers are supported:
    markdown      MarkdownNodeParser; section nodes over max_tokens are
                  sub-split with SentenceSplitter using config.overlap.
    sentence      SentenceSplitter directly (no markdown awareness).
    hierarchical  HierarchicalNodeParser (multi-level chunking).

Chunks below `min_chunk_chars` are dropped (filters TOC/page-number debris).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from llama_index.core.node_parser import (
    HierarchicalNodeParser,
    MarkdownNodeParser,
    SentenceSplitter,
)
from llama_index.core.schema import Document, TextNode

ParserName = Literal["markdown", "sentence", "hierarchical"]


@dataclass(frozen=True)
class ChunkConfig:
    parser: ParserName = "markdown"
    max_tokens: int = 512
    overlap: int = 64
    min_chunk_chars: int = 80


@dataclass
class Chunk:
    text: str
    heading_path: str | None
    token_count: int
    chunk_index: int


def _token_counter(splitter: SentenceSplitter):
    """Return a tokenizer callable from a SentenceSplitter (handles version drift)."""
    fn = getattr(splitter, "_tokenizer", None) or getattr(splitter, "tokenizer", None)
    if fn is None:
        # llama_index >= 0.13 sometimes exposes via _token_size
        return lambda text: len(text.split())
    return lambda text: len(fn(text))


def _heading_path_for(node: TextNode) -> str | None:
    md = node.metadata or {}
    return md.get("header_path") or md.get("heading_path") or md.get("section") or None


def _post_split(node: TextNode, splitter: SentenceSplitter, max_tokens: int, count) -> list[TextNode]:
    """If a node is over max_tokens, split it; otherwise return as-is."""
    if count(node.text) <= max_tokens:
        return [node]
    sub_texts = splitter.split_text(node.text)
    heading = _heading_path_for(node)
    out: list[TextNode] = []
    for sub in sub_texts:
        sub_node = TextNode(text=sub)
        if heading is not None:
            sub_node.metadata["header_path"] = heading
        out.append(sub_node)
    return out


def chunk_markdown(text: str, config: ChunkConfig | None = None) -> list[Chunk]:
    """Split `text` into Chunks per `config`. Markdown by default."""
    cfg = config or ChunkConfig()
    splitter = SentenceSplitter(chunk_size=cfg.max_tokens, chunk_overlap=cfg.overlap)
    count = _token_counter(splitter)

    if cfg.parser == "sentence":
        sub_texts = splitter.split_text(text)
        nodes = [TextNode(text=t) for t in sub_texts]
    elif cfg.parser == "hierarchical":
        parser = HierarchicalNodeParser.from_defaults(
            chunk_sizes=[cfg.max_tokens, max(cfg.max_tokens // 2, 128)]
        )
        nodes = parser.get_nodes_from_documents([Document(text=text)])
        # Hierarchical returns multi-level nodes; keep only leaves
        nodes = [n for n in nodes if not getattr(n, "child_nodes", None)]
    else:  # markdown
        parser = MarkdownNodeParser()
        sections = parser.get_nodes_from_documents([Document(text=text)])
        nodes = []
        for section in sections:
            nodes.extend(_post_split(section, splitter, cfg.max_tokens, count))

    out: list[Chunk] = []
    for i, node in enumerate(nodes):
        body = (node.text or "").strip()
        if len(body) < cfg.min_chunk_chars:
            continue
        out.append(
            Chunk(
                text=body,
                heading_path=_heading_path_for(node),
                token_count=count(body),
                chunk_index=len(out),
            )
        )
    return out
