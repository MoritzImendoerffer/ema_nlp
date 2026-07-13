#!/usr/bin/env python
"""Curate + build precomputed topic subgraphs (docs/next/topic_subgraphs.md).

Subcommands (all read the hubs file resolved by the config search path —
``$EMA_CONFIG_DIR/hubs/<name>.yaml`` shadows ``harness/configs/hubs/`` — or an
explicit ``--file``):

    propose   Rank hub candidates by explainable qualified-fanout score
              (curated links x2 + inline links, archive/news + audience
              penalties) and APPEND them to the hubs file as `status: proposed`.
              A human reviews (`report`) and confirms; nothing is built from a
              proposal.
    confirm   Flip one hub's status to `confirmed` (comment-preserving text edit).
    report    Walk each hub (proposed ones too — this is the pre-confirmation
              preview) and print size + category/doc_type composition, flagging
              oversized subgraphs. Read-only.
    build     Walk every CONFIRMED hub and stamp membership into Mongo
              `document_metadata` (`topic_hubs` + provenance w/ config_hash).
              Then run scripts/propagate_metadata_to_graph.py to patch the live
              graph (or rebuild — ingest joins the same rows).

Requires the Neo4j graph + Mongo up (scripts/start_services.sh). Membership is
stale after any LINKS_TO rebuild — re-run `build` (the stamped config_hash +
stamped_at make violations detectable).

Examples:
    python scripts/manage_topic_hubs.py report
    python scripts/manage_topic_hubs.py propose --top 10
    python scripts/manage_topic_hubs.py confirm gvp
    python scripts/manage_topic_hubs.py build
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

log = logging.getLogger("manage_topic_hubs")

# Default qualifier for `propose` (per-hub walks carry their own in the YAML).
_PROPOSE_CATEGORIES = ["qa", "scientific_guideline", "regulatory_procedure", "regulatory_overview"]


def _store():
    from harness.indexing.property_graph import neo4j_store_from_env

    return neo4j_store_from_env()


def _hubs_path(args) -> Path:
    from harness.retrieval.hubs import hubs_config_path

    return Path(args.file) if args.file else hubs_config_path(args.hubs)


def _load(args):
    from harness.retrieval.hubs import load_hubs

    path = _hubs_path(args)
    return load_hubs(path.stem, config_dir=path.parent), path


def cmd_propose(args) -> None:
    from harness.indexing.subgraphs import key_for_url, propose_candidates
    from harness.retrieval.hubs import proposal_snippet

    config, path = _load(args)
    known_urls = {h.seed_url for h in config.hubs}
    known_keys = set(config.keys())
    candidates = propose_candidates(
        _store(), categories=_PROPOSE_CATEGORIES, min_fanout=args.min_fanout, limit=args.top * 3
    )
    fresh = [c for c in candidates if c.url not in known_urls][: args.top]
    if not fresh:
        print("no new candidates above the fanout threshold")
        return
    print(f"{'score':>7}  {'curated':>7}  {'inline':>6}  title")
    snippets: list[str] = []
    for c in fresh:
        flag = f"  [penalized: {c.penalized}]" if c.penalized else ""
        print(f"{c.score:7.1f}  {c.curated_links:7d}  {c.inline_links:6d}  {c.title}{flag}")
        print(f"{'':25s}{c.url}")
        key = key_for_url(c.url, known_keys)
        known_keys.add(key)
        snippets.append(
            proposal_snippet(key=key, seed_url=c.url, title=c.title, score=c.score)
        )
    if args.dry_run:
        print(f"\n(dry run — nothing appended to {path})")
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(snippets))
    from harness.retrieval.hubs import load_hubs

    load_hubs(path.stem, config_dir=path.parent)  # re-validate: the append must parse
    print(f"\nappended {len(snippets)} proposal(s) to {path} — review, then `confirm <key>`")


def cmd_confirm(args) -> None:
    from harness.retrieval.hubs import confirm_in_text, load_hubs

    config, path = _load(args)
    if config.get(args.key) is None:
        sys.exit(f"unknown hub key {args.key!r}; known: {config.keys()}")
    path.write_text(confirm_in_text(path.read_text(encoding="utf-8"), args.key), encoding="utf-8")
    load_hubs(path.stem, config_dir=path.parent)  # re-validate the edited file
    print(f"hub {args.key!r} confirmed in {path} — run `build` to stamp membership")


def cmd_report(args) -> None:
    from harness.indexing.subgraphs import build_memberships, composition_histogram

    config, _ = _load(args)
    hubs = [h for h in config.hubs if not args.key or h.key in args.key]
    if not hubs:
        sys.exit(f"no hubs match {args.key}; known: {config.keys()}")
    per_hub = build_memberships(_store(), hubs)
    for hub in hubs:
        members = per_hub[hub.key]
        size_flag = "  ⚠ OVERSIZED — tighten the walk qualifier" if len(members) > args.max_size else ""
        print(f"\n=== {hub.key} [{hub.status}] — {len(members)} members "
              f"(hops={hub.walk.hops}){size_flag}")
        print(f"    seed: {hub.seed_url}")
        for label in ("category", "doc_type"):
            hist = composition_histogram(members, label)
            print(f"    by {label}:")
            for value, n in hist.most_common(15):
                print(f"      {value:40s} {n}")


def cmd_build(args) -> None:
    from harness.indexing.document_metadata import upsert_topic_hubs
    from harness.indexing.subgraphs import build_memberships, invert_memberships

    config, _ = _load(args)
    confirmed = config.confirmed()
    if not confirmed:
        sys.exit("no confirmed hubs — `confirm <key>` first (only confirmed hubs are built)")
    per_hub = build_memberships(_store(), confirmed)
    url_to_keys = invert_memberships(per_hub)
    for hub in confirmed:
        print(f"{hub.key}: {len(per_hub[hub.key])} members")
    if args.dry_run:
        print(f"(dry run — {len(url_to_keys)} membership rows NOT written)")
        return
    n = upsert_topic_hubs(
        url_to_keys,
        hub_keys=[h.key for h in confirmed],
        config_hash=config.config_hash(),
    )
    print(
        f"stamped {n} membership rows (config_hash {config.config_hash()}) — now run\n"
        "  python scripts/propagate_metadata_to_graph.py\n"
        "to patch the live graph (new builds join the rows at ingest)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hubs", default="default", help="hubs file name (default: default)")
    parser.add_argument("--file", default=None, help="explicit hubs file path (overrides --hubs)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("propose", help="rank + append hub candidates (status: proposed)")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--min-fanout", type=int, default=5)
    p.add_argument("--dry-run", action="store_true", help="print candidates, append nothing")
    p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("confirm", help="flip one hub to status: confirmed")
    p.add_argument("key")
    p.set_defaults(fn=cmd_confirm)

    p = sub.add_parser("report", help="walk hubs (read-only) — size + composition preview")
    p.add_argument("--key", action="append", help="limit to specific hub key(s)")
    p.add_argument("--max-size", type=int, default=500, help="flag subgraphs larger than this")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("build", help="stamp membership for all CONFIRMED hubs into Mongo")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_build)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args.fn(args)


if __name__ == "__main__":
    main()
