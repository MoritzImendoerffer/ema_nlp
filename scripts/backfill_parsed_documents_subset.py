"""Populate a small ``parsed_documents`` subset from the legacy collections.

The canonical ``parsed_documents`` collection was never backfilled on this host
(see work unit 20 / LIR-007 blocker: live Mongo has only ``web_items`` +
``parsed_pdfs``). This one-off seeds a coherent subset so the LlamaIndex-first
pipeline can be verified end-to-end on CPU:

  * HTML pages -> trafilatura -> ParsedDocument(parser="trafilatura")
  * the PDFs those pages link to (and that exist in ``parsed_pdfs``) ->
    ParsedDocument(parser="pymupdf4llm", text = parsed_pdfs.markdown)

Picking HTML pages by their resolvable PDF links means ``links_to`` edges land
inside the subset. Idempotent via the parsed_documents compound-key upsert.

    python scripts/backfill_parsed_documents_subset.py --dry-run
    python scripts/backfill_parsed_documents_subset.py --max-html 15 --max-pdf 35
"""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
from datetime import UTC, datetime
from pathlib import Path

import trafilatura
from pymongo import MongoClient

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from config import MONGO_DB, MONGO_URI  # noqa: E402
from corpus.parsers.base import ParsedDocument  # noqa: E402
from corpus.sources.parsed_documents import bootstrap_indexes, write_parsed_document  # noqa: E402
from harness.indexing.links import extract_links  # noqa: E402


def _html_to_markdown(html: str) -> str:
    for kwargs in ({"output_format": "markdown"}, {"output_format": "txt"}, {}):
        try:
            out = trafilatura.extract(html, **kwargs)
        except TypeError:
            continue
        if out:
            return out
    return ""


def select_subset(db, *, max_html: int, max_pdf: int, scan_limit: int):
    chosen_html: dict[str, str] = {}
    chosen_pdf: set[str] = set()
    scanned = 0
    cur = db.web_items.find({"html_raw.0": {"$exists": True}}, {"url": 1, "html_raw": 1})
    for d in cur:
        if scanned >= scan_limit:
            break
        if len(chosen_html) >= max_html and len(chosen_pdf) >= max_pdf:
            break
        scanned += 1
        url_field = d.get("url")
        url = url_field[0] if isinstance(url_field, list) else url_field
        if not url:
            continue
        html = d["html_raw"][0]
        pdf_targets = [
            link.tgt_url
            for link in extract_links(html, url)
            if link.kind == "file" and link.tgt_url.lower().endswith(".pdf")
        ]
        resolvable = [
            u for u in pdf_targets
            if db.parsed_pdfs.count_documents({"_id": u, "error": ""}, limit=1)
        ]
        if not resolvable or len(chosen_html) >= max_html:
            continue
        chosen_html[url] = html
        for u in resolvable[:5]:
            if len(chosen_pdf) < max_pdf:
                chosen_pdf.add(u)
    return chosen_html, chosen_pdf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-html", type=int, default=15)
    ap.add_argument("--max-pdf", type=int, default=35)
    ap.add_argument("--scan-limit", type=int, default=1500)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    client: MongoClient = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    html_docs, pdf_urls = select_subset(
        db, max_html=args.max_html, max_pdf=args.max_pdf, scan_limit=args.scan_limit
    )
    print(f"selected {len(html_docs)} HTML pages + {len(pdf_urls)} resolvable PDFs")
    for u in list(html_docs)[:5]:
        print("  html:", u)
    if args.dry_run:
        return

    bootstrap_indexes(client=client)
    now = datetime.now(UTC)
    tv = importlib.metadata.version("trafilatura")
    pv = importlib.metadata.version("pymupdf4llm")
    written = 0

    for url, html in html_docs.items():
        text = _html_to_markdown(html)
        if not text.strip():
            continue
        write_parsed_document(
            ParsedDocument(url=url, parser="trafilatura", parser_version=tv, parsed_at=now,
                           content_type="text/html", text=text, text_format="markdown"),
            client=client,
        )
        written += 1

    for url in pdf_urls:
        pp = db.parsed_pdfs.find_one({"_id": url, "error": ""})
        md = (pp or {}).get("markdown", "") or ""
        if not md.strip():
            continue
        write_parsed_document(
            ParsedDocument(url=url, parser="pymupdf4llm", parser_version=pv, parsed_at=now,
                           content_type="application/pdf", text=md, text_format="markdown"),
            client=client,
        )
        written += 1

    print(f"wrote {written} parsed_documents; collection now: {db.parsed_documents.count_documents({})}")
    client.close()


if __name__ == "__main__":
    main()
