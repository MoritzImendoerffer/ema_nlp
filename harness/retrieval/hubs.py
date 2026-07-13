"""Topic-hub seed list — schema, loader, validation (pure data, no store).

A *hubs file* (``harness/configs/hubs/<name>.yaml``, shadowable via
``$EMA_CONFIG_DIR/hubs/``) lists EMA topic hub pages whose qualified ``LINKS_TO``
fan-out defines a precomputed topic subgraph (docs/next/topic_subgraphs.md).
The loader is strict: a hubs file that cannot do what it declares must not load
(same honesty rule as routing tables). Seed URLs can only be verified against
the live graph, so that check is a separate hook (:func:`validate_seeds`) run by
``scripts/manage_topic_hubs.py`` at build/report time — tests mock the resolver.

The build side (walk + membership stamps) lives in
:mod:`harness.indexing.subgraphs`; the query side (member catalog + budgeted
chunks) in :mod:`harness.retrieval.subgraphs`. This module also carries the
*textual* YAML edit helpers (:func:`proposal_snippet`, :func:`confirm_in_text`)
so ``manage_topic_hubs.py`` can append proposals / flip statuses without
rewriting the file and destroying its comments.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from harness.retrieval.doc_categories import CATEGORIES

log = logging.getLogger(__name__)

STATUSES = ("confirmed", "proposed")
PROPOSERS = ("sme", "agent", "discovery")

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class HubWalk:
    """Per-hub walk bounds: hop count + the node qualifier that keeps it sane.

    A node on the walk qualifies when its ``category`` is in ``categories`` OR
    its ``doc_type`` is in ``doc_types`` (PDFs carry ``doc_type``, HTML detail
    pages only ``category`` — a doc_type-only qualifier would silently drop
    every HTML detail page, §2 of the plan). ``exclude_audience`` drops nodes
    by their EMA audience badge.
    """

    hops: int = 2
    categories: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    exclude_audience: tuple[str, ...] = ()


@dataclass(frozen=True)
class HubSpec:
    """One seed-list entry (see ``configs/hubs/default.yaml`` for field docs)."""

    key: str
    seed_url: str
    status: str = "proposed"
    proposed_by: str = "sme"
    title: str = ""
    walk: HubWalk = field(default_factory=HubWalk)


@dataclass
class HubsConfig:
    """A loaded hubs file: the full seed list plus lookup helpers."""

    name: str
    hubs: list[HubSpec] = field(default_factory=list)

    def get(self, key: str) -> HubSpec | None:
        return next((h for h in self.hubs if h.key == key), None)

    def keys(self) -> list[str]:
        return [h.key for h in self.hubs]

    def confirmed(self) -> list[HubSpec]:
        """Only confirmed hubs are ever built into membership stamps."""
        return [h for h in self.hubs if h.status == "confirmed"]

    def config_hash(self) -> str:
        """Stable hash of the *build-relevant* config (seeds + walks of confirmed
        hubs) — stamped into ``provenance.topic_hubs`` so a membership built from
        a different config (or before a walk-param change) is detectable."""
        payload = [
            {
                "key": h.key,
                "seed_url": h.seed_url,
                "hops": h.walk.hops,
                "categories": sorted(h.walk.categories),
                "doc_types": sorted(h.walk.doc_types),
                "exclude_audience": sorted(h.walk.exclude_audience),
            }
            for h in sorted(self.confirmed(), key=lambda h: h.key)
        ]
        blob = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


def _walk_from_dict(key: str, d: dict | None) -> HubWalk:
    d = d or {}
    hops = int(d.get("hops", 2))
    if hops < 1:
        raise ValueError(f"hub {key!r}: walk.hops must be >= 1, got {hops}")
    categories = tuple(str(c) for c in (d.get("categories") or []))
    doc_types = tuple(str(t) for t in (d.get("doc_types") or []))
    unknown = [c for c in categories if c not in CATEGORIES]
    if unknown:
        raise ValueError(
            f"hub {key!r}: walk.categories has unknown categor(ies) {unknown}; "
            f"valid: {list(CATEGORIES)}"
        )
    if not categories and not doc_types:
        # An unqualified walk is the news-pollution trap the plan's §2 evidence
        # warns about — require at least one qualifier list.
        raise ValueError(
            f"hub {key!r}: walk needs a qualifier — walk.categories and/or "
            "walk.doc_types must be non-empty"
        )
    return HubWalk(
        hops=hops,
        categories=categories,
        doc_types=doc_types,
        exclude_audience=tuple(str(a) for a in (d.get("exclude_audience") or [])),
    )


def _hub_from_dict(d: dict) -> HubSpec:
    key = str(d.get("key") or "")
    if not _KEY_RE.fullmatch(key):
        raise ValueError(f"hub key {key!r} must match {_KEY_RE.pattern}")
    seed_url = str(d.get("seed_url") or "")
    if not seed_url.startswith(("http://", "https://")):
        raise ValueError(f"hub {key!r}: seed_url must be an absolute http(s) URL")
    status = str(d.get("status", "proposed"))
    if status not in STATUSES:
        raise ValueError(f"hub {key!r}: unknown status {status!r}; valid: {list(STATUSES)}")
    proposed_by = str(d.get("proposed_by", "sme"))
    if proposed_by not in PROPOSERS:
        raise ValueError(
            f"hub {key!r}: unknown proposed_by {proposed_by!r}; valid: {list(PROPOSERS)}"
        )
    return HubSpec(
        key=key,
        seed_url=seed_url,
        status=status,
        proposed_by=proposed_by,
        title=str(d.get("title") or ""),
        walk=_walk_from_dict(key, d.get("walk")),
    )


def hubs_config_path(name: str = "default", *, config_dir: Path | None = None) -> Path:
    """Resolve ``hubs/<name>.yaml`` on the config search path (explicit dir wins)."""
    if config_dir is not None:
        path = config_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Hubs file not found: {path}")
        return path
    from harness.config_paths import find_config

    found = find_config("hubs", f"{name}.yaml")
    if found is None:
        raise FileNotFoundError(
            f"Hubs file not found: {name!r} (searched $EMA_CONFIG_DIR/hubs "
            "and the built-in hubs/)"
        )
    return found


def load_hubs(name: str = "default", *, config_dir: Path | None = None) -> HubsConfig:
    """Load and validate ``hubs/<name>.yaml`` into a :class:`HubsConfig`."""
    path = hubs_config_path(name, config_dir=config_dir)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = raw.get("hubs", raw) if isinstance(raw, dict) else raw
    hubs = [_hub_from_dict(d or {}) for d in (section or [])]
    seen: set[str] = set()
    for hub in hubs:
        if hub.key in seen:
            raise ValueError(f"hubs file {name!r} has duplicate hub key {hub.key!r}")
        seen.add(hub.key)
    log.info(
        "loaded hubs file %r: %d hubs (%d confirmed)",
        name, len(hubs), sum(1 for h in hubs if h.status == "confirmed"),
    )
    return HubsConfig(name=name, hubs=hubs)


def validate_seeds(config: HubsConfig, resolve: Callable[[str], bool]) -> None:
    """Fail loudly when a seed URL does not resolve to a ``:Document``.

    ``resolve(url) -> bool`` is store-backed at runtime (mocked in tests).
    EMA reorganizations silently break URLs — a dangling seed must be a hard
    error at build/report time, never a silent empty subgraph.
    """
    missing = [h.key for h in config.hubs if not resolve(h.seed_url)]
    if missing:
        raise ValueError(
            f"hub seed URL(s) do not resolve to a :Document in the graph: {missing} "
            "— fix the seed_url (EMA may have moved the page) or rebuild the graph"
        )


# ── textual YAML edits (comment-preserving; used by scripts/manage_topic_hubs) ──


def proposal_snippet(
    *,
    key: str,
    seed_url: str,
    title: str = "",
    score: float | None = None,
    walk: HubWalk | None = None,
    proposed_by: str = "discovery",
) -> str:
    """A YAML list-entry block for one proposed hub, appendable to a hubs file.

    Emitted as text (not ``yaml.dump`` of the whole file) so appending never
    destroys the file's comments. Indentation matches the shipped default.yaml.
    """
    w = walk or HubWalk(
        categories=("qa", "scientific_guideline", "regulatory_procedure", "regulatory_overview")
    )
    lines = []
    if title or score is not None:
        score_part = f" (score {score:.1f})" if score is not None else ""
        lines.append(f"  # {title or key}{score_part}")
    lines += [
        f"  - key: {key}",
        f"    seed_url: {seed_url}",
        "    status: proposed",
        f"    proposed_by: {proposed_by}",
        "    walk:",
        f"      hops: {w.hops}",
        f"      categories: [{', '.join(w.categories)}]",
        f"      doc_types: [{', '.join(w.doc_types)}]",
        f"      exclude_audience: [{', '.join(w.exclude_audience) or 'Veterinary, Corporate'}]",
    ]
    return "\n".join(lines) + "\n"


def confirm_in_text(text: str, key: str) -> str:
    """Flip ``status: proposed`` to ``confirmed`` for one hub, preserving comments.

    Operates on the raw file text: finds the ``- key: <key>`` entry and rewrites
    the first ``status:`` line before the next entry. Raises if the hub or its
    status line is missing, or it is already confirmed.
    """
    lines = text.splitlines(keepends=True)
    entry_re = re.compile(r"^\s*-\s*key:\s*(\S+)\s*$")
    start = next(
        (i for i, ln in enumerate(lines) if (m := entry_re.match(ln)) and m.group(1) == key),
        None,
    )
    if start is None:
        raise ValueError(f"hub {key!r} not found in hubs file")
    for i in range(start + 1, len(lines)):
        if entry_re.match(lines[i]):
            break
        m = re.match(r"^(\s*status:\s*)(\S+)\s*$", lines[i])
        if m:
            if m.group(2) == "confirmed":
                raise ValueError(f"hub {key!r} is already confirmed")
            lines[i] = f"{m.group(1)}confirmed\n"
            return "".join(lines)
    raise ValueError(f"hub {key!r} has no status line to confirm")
