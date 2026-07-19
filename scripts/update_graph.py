#!/usr/bin/env python
"""Scraper output -> Neo4j graph: the one pipeline entry point.

Sequences the stages that turn ``ema_scraper`` output into the retrieval
graph. Each stage is an existing, independently-runnable CLI; this script only
orders them, prints each command, and stops on the first failure — so the
pipeline is inspectable and any stage can be re-run by hand.

    scrape (ema_scraper, separate project)
      -> Mongo web_items (raw HTML) + Scrapy disk cache (parsed_pdf.pkl per PDF)

    1. parse-html   python -m corpus.parsers.trafilatura      -> parsed_documents
    2. parse-pdfs   python -m corpus.parsers.pymupdf4llm      -> parsed_documents
                    (needs --pdf-cache pointing at the Scrapy cache root)
    3. enrich       scripts/enrich_document_metadata.py       -> document_metadata
                    (badges from web_items + doc_type from the EMA JSON export)
    4. build        python -m harness.indexing.build          -> Neo4j graph
                    (embeds chunks — hours on GPU for the full corpus; resumable,
                    re-run to continue after a crash. Ingest joins
                    document_metadata, so all labels are stamped at build time.)
    5. subgraphs    scripts/manage_topic_hubs.py build        -> document_metadata
                    (topic-subgraph membership stamps for CONFIRMED hubs;
                    optional — run after any build/links change, then propagate.
                    Kept out of the default steps.)
    6. propagate    scripts/propagate_metadata_to_graph.py    -> Neo4j SET
                    (labels+membership patch of an EXISTING graph; not needed
                    after a fresh build — kept out of the default steps)

Prerequisites: ``scripts/start_services.sh`` (Mongo + Neo4j up), credentials in
``~/Nextcloud/Datasets/ema_nlp/ema_nlp.env``. See docs/RETRIEVAL.md §2 + §6.

Examples:
    # full pipeline after a new scrape (GPU host)
    python scripts/update_graph.py --pdf-cache ~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap \\
        --full --reset --pause-every-docs 2000

    # smoke run: 200 docs end to end on CPU
    python scripts/update_graph.py --steps parse-html,enrich,build --limit 200 --embed-device cpu

    # labels changed (new export / re-scrape), graph otherwise fine:
    python scripts/update_graph.py --steps enrich,propagate

    # resume an interrupted full build (skip parsing + enrichment)
    python scripts/update_graph.py --steps build --full
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

STEPS = ["parse-html", "parse-pdfs", "enrich", "build", "subgraphs", "propagate"]
DEFAULT_STEPS = ["parse-html", "parse-pdfs", "enrich", "build"]


def _run(cmd: list[str], *, dry_run: bool) -> None:
    print(f"\n=== {' '.join(cmd)}")
    if dry_run:
        return
    result = subprocess.run(cmd, cwd=_REPO)  # noqa: S603 (our own CLIs)
    if result.returncode != 0:
        sys.exit(f"step failed (exit {result.returncode}): {' '.join(cmd)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples:")[1],
    )
    parser.add_argument(
        "--steps", default=",".join(DEFAULT_STEPS),
        help=f"comma-separated subset of {STEPS} (default: {','.join(DEFAULT_STEPS)}; "
             "propagate is only for patching an existing graph)",
    )
    parser.add_argument("--pdf-cache", type=Path, default=None,
                        help="Scrapy cache root with parsed_pdf.pkl entries (parse-pdfs step)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap rows/docs in every stage (smoke runs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands without running them")
    build = parser.add_argument_group("build stage (forwarded to harness.indexing.build)")
    build.add_argument("--profile", default=None, help="index profile (default: EMA_INDEX_PROFILE)")
    build.add_argument("--full", action="store_true", help="whole corpus (ignore profile limit)")
    build.add_argument("--reset", action="store_true", help="DETACH DELETE the graph first")
    build.add_argument("--embed-device", default="cuda", help="cuda (default) or cpu")
    build.add_argument("--embed-batch", type=int, default=None)
    build.add_argument("--pause-every-docs", type=int, default=None,
                       help="GPU throttle: flush + pause every N docs (see GPU crash notes)")
    build.add_argument("--pause-seconds", type=float, default=None)
    args = parser.parse_args()

    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        sys.exit(f"unknown step(s) {unknown}; valid: {STEPS}")
    if "parse-pdfs" in steps and args.pdf_cache is None:
        if args.steps == ",".join(DEFAULT_STEPS):
            print("NOTE: no --pdf-cache given — skipping the parse-pdfs step")
            steps.remove("parse-pdfs")
        else:
            sys.exit("--pdf-cache is required for the parse-pdfs step")

    py = sys.executable
    limit = [f"--limit={args.limit}"] if args.limit else []

    for step in steps:
        if step == "parse-html":
            _run([py, "-m", "corpus.parsers.trafilatura", *limit], dry_run=args.dry_run)
        elif step == "parse-pdfs":
            _run(
                [py, "-m", "corpus.parsers.pymupdf4llm", "--cache", str(args.pdf_cache), *limit],
                dry_run=args.dry_run,
            )
        elif step == "enrich":
            _run([py, "scripts/enrich_document_metadata.py", *limit], dry_run=args.dry_run)
        elif step == "build":
            cmd = [py, "-m", "harness.indexing.build", "--embed-device", args.embed_device]
            if args.profile:
                cmd += ["--profile", args.profile]
            if args.full:
                cmd += ["--full"]
            elif args.limit:
                cmd += [f"--limit={args.limit}"]
            if args.reset:
                cmd += ["--reset"]
            if args.embed_batch is not None:
                cmd += [f"--embed-batch={args.embed_batch}"]
            if args.pause_every_docs is not None:
                cmd += [f"--pause-every-docs={args.pause_every_docs}"]
            if args.pause_seconds is not None:
                cmd += [f"--pause-seconds={args.pause_seconds}"]
            _run(cmd, dry_run=args.dry_run)
        elif step == "subgraphs":
            _run([py, "scripts/manage_topic_hubs.py", "build"], dry_run=args.dry_run)
        elif step == "propagate":
            _run([py, "scripts/propagate_metadata_to_graph.py"], dry_run=args.dry_run)
    print("\npipeline complete." if not args.dry_run else "\n(dry run — nothing executed)")


if __name__ == "__main__":
    main()
