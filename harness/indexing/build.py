"""CLI: build the hierarchical PropertyGraphIndex from Mongo into Neo4j.

Batched + resumable (see ``property_graph.build_property_graph_index``): a crash
loses at most one flush; re-run the same command to resume (already-built docs
are skipped). ``LINKS_TO`` edges are a final idempotent pass.

Examples::

    # whole corpus, GPU, fresh build
    python -m harness.indexing.build --full --reset --embed-device cuda

    # resume an interrupted full build (no --reset)
    python -m harness.indexing.build --full --embed-device cuda

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
    ap.add_argument("--reset", action="store_true", help="DETACH DELETE the graph first")
    ap.add_argument("--no-resume", action="store_true", help="do not skip already-built docs")
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
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    configure_embed_model(device=args.embed_device, embed_batch_size=args.embed_batch)

    profile = load_index_profile(args.profile)
    if args.full:
        profile.index.scope.limit = None
    elif args.limit is not None:
        profile.index.scope.limit = args.limit

    logging.info(
        "build start: profile=%s scope.limit=%s device=%s embed_batch=%d flush=%d "
        "pause_every_docs=%d pause_seconds=%.0f reset=%s links_only=%s",
        profile.name, profile.index.scope.limit, args.embed_device,
        args.embed_batch, args.flush_chunks, args.pause_every_docs, args.pause_seconds,
        args.reset, args.links_only,
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
    )
    logging.info("build complete.")


if __name__ == "__main__":
    main()
