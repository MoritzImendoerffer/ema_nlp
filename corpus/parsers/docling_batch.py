"""The batch loop of the ``docling`` parser (backlog row 17, work unit 28, TASK-011).

``scripts/parse_pdfs_docling.py`` is the command; this module holds the loop, so a spawned
worker process can import :func:`process_one` by name.

What one batch does, in order:

1. Read the list: JSONL records with ``url`` and ``cache_path`` (the ranking's output, or
   a cut of it), optionally ``pages`` and ``group``.
2. Select: a document whose folder for these options already holds ``run.json`` is
   skipped, so a batch can be stopped and started again. Documents are taken in list order
   until the next one would exceed the page budget.
3. Parse each selected document in a worker process: Docling, post-processing, the three
   files (``corpus/parsers/docling_store.py``). The worker holds the models and is
   replaced after ``docs_per_worker`` documents. A PDF above ``range_pages`` pages is
   parsed in page ranges and joined.
4. A failed or partial document is listed in ``failures.jsonl`` with its cause; its
   previous folder stays. A worker that dies (a crash in CUDA, the kernel's OOM killer)
   fails only the documents it held, and a new worker takes over.
5. Every ``pause_every`` documents the batch waits ``pause_seconds`` with no document in a
   worker: the GPU rests (its firmware wedged under sustained load in 2026-06, and the
   250 W power cap with pauses held). Between documents the batch stops when the stop file
   exists, so a graph build can have the GPU.

The Mongo row is written only with ``write_mongo``. Batch 0 writes files only.
"""

from __future__ import annotations

import gzip
import json
import multiprocessing
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from corpus.parsers.docling_store import (
    RUN_FILE,
    append_failure,
    doc_id_for,
    mongo_row,
    parse_folder,
    run_record,
    source_sha256,
    write_parse,
)

GZIP_MAGIC = b"\x1f\x8b"
STOP_FILE = "STOP"


def read_pdf(cache_path: str | None) -> bytes:
    """The PDF bytes of a Scrapy cache entry, decompressed when the body is gzip."""
    if not cache_path:
        raise FileNotFoundError("no cache_path")
    raw = (Path(cache_path) / "response_body").read_bytes()
    return gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw


def load_items(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def process_one(item: dict[str, Any], root: str, range_pages: int, write_mongo: bool,
                convert: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Parse, post-process and write one document. Runs in the worker; never raises."""
    from corpus.parsers import docling_pdf
    from corpus.parsers.docling_post import post_process

    url = item["url"]
    out: dict[str, Any] = {"url": url, "group": item.get("group", "")}
    try:
        pdf = read_pdf(item.get("cache_path"))
    except Exception as exc:  # noqa: BLE001
        return {**out, "status": "failed", "doc_id": "", "sha256": "", "error": f"read: {type(exc).__name__}: {exc}"[:500]}
    doc_id, sha = doc_id_for(url, pdf), source_sha256(pdf)
    out.update(doc_id=doc_id, sha256=sha)
    folder = parse_folder(Path(root), doc_id, docling_pdf.OPTIONS_HASH)
    conv = (convert or docling_pdf.convert_pdf)(pdf, url.rsplit("/", 1)[-1] or "document.pdf", range_pages)
    if conv.status != "SUCCESS":
        return {**out, "status": "failed", "error": conv.error, "seconds": round(conv.seconds, 2)}
    try:
        doc, post_counts = post_process(conv.document)
        counts = {**conv.counts, **post_counts}
        run = run_record(url=url, doc_id=doc_id, source_sha=sha, options=docling_pdf.OPTIONS,
                         opts_hash=docling_pdf.OPTIONS_HASH, versions=docling_pdf.package_versions(),
                         counts=counts, seconds=conv.seconds, device=docling_pdf.device())
        write_parse(folder, conv.document, doc, run)
        if write_mongo:
            _write_row(url, doc_id, folder, Path(root), sha, doc, counts)
    except Exception as exc:  # noqa: BLE001
        return {**out, "status": "failed", "error": f"after parse: {type(exc).__name__}: {exc}"[:500],
                "seconds": round(conv.seconds, 2)}
    return {**out, "status": "parsed", "folder": str(folder.relative_to(root)), "pages": conv.pages,
            "seconds": round(conv.seconds, 2), "counts": counts}


def _write_row(url: str, doc_id: str, folder: Path, root: Path, sha: str, doc: dict[str, Any],
               counts: dict[str, int]) -> None:
    from docling_core.types.doc import DoclingDocument

    from corpus.parsers import docling_pdf
    from corpus.sources.parsed_documents import write_parsed_document

    markdown = DoclingDocument.model_validate(doc).export_to_markdown()
    write_parsed_document(mongo_row(url=url, doc_id=doc_id, folder_rel=str(folder.relative_to(root)),
                                    source_sha=sha, markdown=markdown, counts=counts,
                                    docling_version=docling_pdf.docling_version(),
                                    opts_hash=docling_pdf.OPTIONS_HASH))


class _InlineExecutor:
    """Runs a call at submit time, for tests and for ``workers=0``."""

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        fut: Future[Any] = Future()
        try:
            fut.set_result(fn(*args))
        except BaseException as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        return None


@dataclass
class BatchSettings:
    root: Path
    budget_pages: int
    docs_per_worker: int = 50
    workers: int = 1  # 0 runs every document in this process (tests)
    range_pages: int = 100
    pause_every: int = 20
    pause_seconds: float = 60.0
    stop_file: Path | None = None
    write_mongo: bool = False
    log_path: Path | None = None
    convert: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    echo: Callable[[str], None] = print
    summary: dict[str, Any] = field(default_factory=dict)


def select(items: Iterable[dict[str, Any]], s: BatchSettings, opts_hash: str,
           count_pages: Callable[[bytes], int]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The documents to parse: not yet parsed with these options, within the page budget."""
    chosen: list[dict[str, Any]] = []
    stats = {"listed": 0, "skipped_existing": 0, "unreadable": 0, "planned_pages": 0, "budget_reached": 0}
    for item in items:
        stats["listed"] += 1
        try:
            pdf = read_pdf(item.get("cache_path"))
        except Exception:  # noqa: BLE001 — the worker lists it with its cause
            stats["unreadable"] += 1
            chosen.append(item)
            continue
        if (parse_folder(s.root, doc_id_for(item["url"], pdf), opts_hash) / RUN_FILE).exists():
            stats["skipped_existing"] += 1
            continue
        pages = item.get("pages") or count_pages(pdf)
        if stats["planned_pages"] + pages > s.budget_pages:
            stats["budget_reached"] = 1
            break
        stats["planned_pages"] += pages
        chosen.append(item)
    return chosen, stats


def run_batch(items: Iterable[dict[str, Any]], s: BatchSettings) -> dict[str, Any]:
    """Select, parse, list failures, pause and stop as the module docstring says."""
    from corpus.parsers import docling_pdf

    stop_file = s.stop_file or s.root / STOP_FILE
    chosen, stats = select(items, s, docling_pdf.OPTIONS_HASH, docling_pdf.pdf_page_count)
    s.echo(json.dumps({"selected": len(chosen), **stats}))
    totals = {"parsed": 0, "failed": 0, "pages_parsed": 0, "pauses": 0, "worker_restarts": 0,
              "stopped": False, "seconds": 0.0}
    t0 = time.time()
    log = open(s.log_path, "a", encoding="utf-8") if s.log_path else None  # noqa: SIM115

    def make_executor() -> Any:
        if s.workers == 0:
            return _InlineExecutor()
        return ProcessPoolExecutor(max_workers=s.workers, mp_context=multiprocessing.get_context("spawn"),
                                   max_tasks_per_child=s.docs_per_worker)

    def record(res: dict[str, Any]) -> None:
        res["at"] = datetime.now(UTC).isoformat(timespec="seconds")
        if res["status"] == "parsed":
            totals["parsed"] += 1
            totals["pages_parsed"] += res.get("pages", 0)
        else:
            totals["failed"] += 1
            append_failure(s.root, url=res["url"], doc_id=res.get("doc_id", ""), sha256=res.get("sha256", ""),
                           error=res.get("error", ""))
        if log:
            log.write(json.dumps(res, ensure_ascii=False) + "\n")
            log.flush()
        s.echo(json.dumps({k: res.get(k) for k in ("status", "url", "pages", "seconds", "error") if res.get(k) is not None}))

    executor = make_executor()
    queue = iter(chosen)
    pending: dict[Future[Any], dict[str, Any]] = {}
    since_pause = 0
    exhausted = False
    try:
        while True:
            while not exhausted and not totals["stopped"] and len(pending) < max(s.workers, 1):
                if s.pause_every and since_pause >= s.pause_every:
                    if pending:
                        break  # the pause starts once no document is in a worker
                    s.sleep(s.pause_seconds)
                    totals["pauses"] += 1
                    since_pause = 0
                if stop_file.exists():
                    totals["stopped"] = True
                    s.echo(json.dumps({"stop_file": str(stop_file)}))
                    break
                item = next(queue, None)
                if item is None:
                    exhausted = True
                    break
                args = (item, str(s.root), s.range_pages, s.write_mongo)
                pending[executor.submit(process_one, *args, *((s.convert,) if s.convert else ()))] = item
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            broken = False
            for fut in done:
                item = pending.pop(fut)
                try:
                    res = fut.result()
                except BrokenProcessPool as exc:
                    broken = True
                    res = {"url": item["url"], "group": item.get("group", ""), "status": "failed",
                           "error": f"worker died: {exc}"[:500]}
                record(res)
                since_pause += 1
            if broken:
                for fut, item in list(pending.items()):
                    record({"url": item["url"], "group": item.get("group", ""), "status": "failed",
                            "error": "worker pool broken by another document"})
                    pending.pop(fut)
                executor.shutdown(wait=False, cancel_futures=True)
                executor = make_executor()
                totals["worker_restarts"] += 1
    finally:
        executor.shutdown(wait=True)
        if log:
            log.close()
    totals["seconds"] = round(time.time() - t0, 1)
    summary = {"selected": len(chosen), **stats, **totals}
    s.echo(json.dumps(summary))
    return summary
