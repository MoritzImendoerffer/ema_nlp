"""CLI: build the hierarchical PropertyGraphIndex from Mongo into Neo4j.

Batched + resumable (see ``property_graph.build_property_graph_index``): a crash
loses at most one flush. A re-run compares each document with its selected
parse: unchanged documents are skipped, changed ones replaced. ``LINKS_TO``
edges are a final idempotent pass.

Examples::

    # refresh the graph: build new documents, replace changed ones (no deletes
    # beyond the replaced documents' old chunks)
    python -m harness.indexing.build --full --embed-device cuda

    # WARNING: --reset DELETES every :Document and :Chunk node of the live graph
    # (79,882 documents, 7.4 million chunks on 2026-11-25) before rebuilding; a full
    # rebuild embeds for hours on the GPU. Other nodes, such as the NeoDash
    # dashboard, stay.
    python -m harness.indexing.build --full --reset --embed-device cuda

    # also DELETE the documents whose URL has no clean row in parsed_documents
    python -m harness.indexing.build --full --prune

    # a 500-doc slice for quick iteration
    python -m harness.indexing.build --limit 500

    # rebuild only the LINKS_TO edges over an existing graph
    python -m harness.indexing.build --full --links-only
"""

from __future__ import annotations

import argparse
import logging

from llama_index.core import Settings

from harness.indexing import load_index_profile
from harness.indexing.registry import build_index
from harness.providers import configure_embed_model


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Neo4j PropertyGraphIndex from Mongo.")
    ap.add_argument("--profile", default=None, help="index profile (default: EMA_INDEX_PROFILE)")
    ap.add_argument("--full", action="store_true", help="ignore profile scope.limit (whole corpus)")
    ap.add_argument("--limit", type=int, default=None, help="cap documents (overrides profile)")
    ap.add_argument(
        "--reset", action="store_true",
        help="DELETE every Document and Chunk node first, in batches (other nodes stay); "
             "then rebuild",
    )
    ap.add_argument(
        "--prune", action="store_true",
        help="DELETE the documents whose URL has no clean row in parsed_documents "
             "(compared with all clean URLs, whatever --limit says); prints the count first",
    )
    ap.add_argument(
        "--no-resume", action="store_true",
        help="replace every document: delete its chunks and build it again",
    )
    ap.add_argument("--flush-chunks", type=int, default=4000, help="chunks per embed/upsert flush")
    ap.add_argument("--embed-device", default="cuda", help="torch device for embeddings (cuda/cpu)")
    ap.add_argument("--embed-batch", type=int, default=128, help="embedding model batch size")
    ap.add_argument(
        "--pause-every-docs", type=int, default=0,
        help="flush then sleep --pause-seconds after every N new docs (0=never); throttles the GPU",
    )
    ap.add_argument(
        "--pause-seconds", type=float, default=60.0,
        help="seconds to sleep at each doc-batch pause (see --pause-every-docs)",
    )
    ap.add_argument("--links-only", action="store_true", help="(re)build only LINKS_TO edges")
    ap.add_argument(
        "--reset-links", action="store_true",
        help="delete existing LINKS_TO edges first, then re-extract (implies --links-only; "
             "chunks/vectors untouched)",
    )
    args = ap.parse_args()
    if args.reset_links:
        args.links_only = True

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    profile = load_index_profile(args.profile)
    # The profile's embed_model is the single source of truth for the embedding
    # space (F12/R3-Q1) — device/batch stay CLI/runtime concerns.
    configure_embed_model(
        profile.index.embed_model, device=args.embed_device, embed_batch_size=args.embed_batch
    )
    if args.full:
        profile.index.scope.limit = None
    elif args.limit is not None:
        profile.index.scope.limit = args.limit

    logging.info(
        "build start: profile=%s scope.limit=%s device=%s embed_batch=%d flush=%d "
        "pause_every_docs=%d pause_seconds=%.0f reset=%s prune=%s links_only=%s reset_links=%s",
        profile.name, profile.index.scope.limit, args.embed_device,
        args.embed_batch, args.flush_chunks, args.pause_every_docs, args.pause_seconds,
        args.reset, args.prune, args.links_only, args.reset_links,
    )
    build_index(
        profile,
        embed_model=Settings.embed_model,
        reset=args.reset,
        resume=not args.no_resume,
        flush_chunks=args.flush_chunks,
        pause_every_docs=args.pause_every_docs,
        pause_seconds=args.pause_seconds,
        links_only=args.links_only,
        reset_links=args.reset_links,
        prune=args.prune,
    )
    logging.info("build complete.")


if __name__ == "__main__":
    main()
