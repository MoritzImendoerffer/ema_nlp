#!/usr/bin/env python
"""Seed / dump the NeoDash dashboard node in Neo4j.

NeoDash persists dashboards as ``:_Neodash_Dashboard`` nodes whose ``content``
property holds the dashboard JSON. This script round-trips the committed
``deploy/neo4j/neodash_dashboard.json``:

    python scripts/seed_neodash.py                # file → Neo4j (MERGE by title)
    python scripts/seed_neodash.py --dump         # Neo4j → file (after UI edits)
    python scripts/seed_neodash.py --dump --title "EMA KB"

Workflow: edit the dashboard in the NeoDash UI (http://localhost:5005), save it
to Neo4j from the UI, then ``--dump`` and commit the JSON. ``seed`` restores it
on any fresh instance. Connection env as in scripts/inspect_graph.py.

Node shape verified against the NeoDash 2.4.11 source (DashboardThunks.ts):
``uuid`` is the MERGE key and what the load dialog passes to the loader — a
node without it lists fine but fails to load ("A dashboard with UUID 'null'
does not exist"). The uuid lives both on the node and inside ``content``
(NeoDash writes it into the dashboard JSON before saving); the committed file
carries it, so reseeding is idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

DEFAULT_FILE = _REPO / "deploy" / "neo4j" / "neodash_dashboard.json"


def _driver():
    from neo4j import GraphDatabase

    import config  # noqa: F401  (loads ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env)

    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError(
            "NEO4J_PASSWORD is not set. Configure it in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env "
            "(never hardcode credentials)."
        )
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), password),
    )


def seed(session, path: Path, user: str) -> str:
    import uuid as uuidlib

    dashboard = json.loads(path.read_text(encoding="utf-8"))
    title = dashboard.get("title") or "EMA KB"
    if not dashboard.get("uuid"):
        # Stable per title, so reseeding never duplicates the node.
        dashboard["uuid"] = str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, f"ema-neodash:{title}"))
    session.run(
        "MERGE (d:`_Neodash_Dashboard` {uuid: $uuid}) "
        "SET d.title = $title, d.date = datetime(), d.user = $user, "
        "    d.version = $version, d.content = $content "
        "WITH d MATCH (stale:`_Neodash_Dashboard` {title: $title}) "
        "WHERE stale.uuid IS NULL DETACH DELETE stale",
        uuid=dashboard["uuid"],
        title=title,
        user=user,
        version=str(dashboard.get("version") or "2.4"),
        content=json.dumps(dashboard, ensure_ascii=False),
    )
    return title


def dump(session, path: Path, title: str | None) -> str:
    q = "MATCH (d:`_Neodash_Dashboard`) "
    if title:
        q += "WHERE d.title = $title "
    q += "RETURN d.title AS title, d.content AS content ORDER BY d.date DESC LIMIT 1"
    record = session.run(q, title=title).single()
    if record is None:
        raise SystemExit("No _Neodash_Dashboard node found — save one from the NeoDash UI first.")
    path.write_text(
        json.dumps(json.loads(record["content"]), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record["title"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--dump", action="store_true", help="Neo4j → file instead of file → Neo4j")
    parser.add_argument("--title", default=None, help="dashboard title to dump (default: latest)")
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    args = parser.parse_args(argv)

    with _driver() as driver, driver.session() as session:
        if args.dump:
            title = dump(session, args.file, args.title)
            print(f"dumped dashboard {title!r} → {args.file}")
        else:
            title = seed(session, args.file, args.user)
            print(f"seeded dashboard {title!r} from {args.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
