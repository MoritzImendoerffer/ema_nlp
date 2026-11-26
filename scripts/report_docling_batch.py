#!/usr/bin/env python
"""Report on one batch of the ``docling`` parser (backlog row 17, work unit 28, TASK-012).

Reads the batch list, the parse folders under ``config.PARSED_ROOT``, ``failures.jsonl``,
the PDFs' text layers (pymupdf) and the legacy rows of the same URLs (MongoDB, read-only).
Runs in .venv: it reads ``doc.json`` as plain JSON and needs no Docling. Writes
``report_<list>.json`` and ``report_<list>.md`` under ``config.RESULTS_DIR/docling``.

What it measures, each per group of the list (``ranked``, ``random``) with n:

- **Rates.** Seconds per page for documents without tables, and a least-squares fit
  ``seconds = a x pages without tables + b x tables + c x cells`` (no intercept).
- **Failures.** Every listed document with a failure and no parse folder, with its cause.
- **Sizes.** Bytes per page of each file, plain and gzip (level 6).
- **Post-processing.** Tables joined, footnote marks, footnotes attached, markup converted,
  reference numbers lifted.
- **Table numbers.** For each table on a page with a text layer (50 characters or more):
  the share of the layer's numbers inside the table's box that the cells hold, and the share
  of the cells' numbers that the layer holds. A layer number equal to a cell's number
  followed by its footnote mark's digits (layer ``12.51``, cell ``12.5[^1]``) is the layer
  flattening the mark; such pairs are counted in their own column and left out of both
  shares. The check cannot see a number in the wrong cell.
- **Greek letters and the micro sign**, held against the text layer, for page text and for
  tables. The line rule: a Greek letter on a line without a run of 3 or more Greek letters is
  a symbol in Latin text; the others are Greek-language letters. A "line" is a text line of
  the layer, a text item of Docling's page text, and a cell of a table. Also the Greek
  letters returned that the layer lacks.
- **CJK characters** in the output (the OCR model is multilingual).
- **Words and numbers held** against the legacy text of the same document.

All texts are NFKC-normalised first, so the micro sign (U+00B5) and mu (U+03BC) count as one.
Held = sum over tokens of min(count in reference, count in output).

Usage::

    .venv/bin/python scripts/report_docling_batch.py <list.jsonl>
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from corpus.parsers.docling_batch import load_items, read_pdf  # noqa: E402
from corpus.parsers.docling_store import (  # noqa: E402
    DOC_FILE,
    FAILURES_FILE,
    RAW_FILE,
    RUN_FILE,
    doc_id_for,
    parse_folder,
)

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
WORD = re.compile(r"[^\W\d_]{2,}")
MARK = re.compile(r"\[\^[^\]\s]{1,4}\]")
MARKED_NUMBER = re.compile(r"(\d+(?:[.,]\d+)*)\[\^(\d{1,3})\]")
GREEK = {chr(c) for c in range(0x391, 0x3AA)} | {chr(c) for c in range(0x3B1, 0x3CA)}
GREEK_RUN = re.compile("[" + "".join(sorted(GREEK)) + "]{3,}")
MU = "μ"
CJK = re.compile(r"[　-鿿가-힯＀-￯]")
NO_TEXT_CHARS = 50
POST_COUNTS = ("tables_joined", "footnote_marks", "footnotes_attached", "markup_converted", "header_reference_lifted")
LEGACY_QUERY = {"parser": "pymupdf4llm", "parser_version": "legacy", "error": ""}


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def held(ref: Counter[str], out: Counter[str]) -> int:
    return sum(min(n, out[k]) for k, n in ref.items())


def share(h: int, n: int) -> float | None:
    return round(h / n, 4) if n else None


def strip_marks(text: str) -> str:
    return MARK.sub(" ", text)


# ── Greek letters by the line rule ───────────────────────────────────────────


def greek_split(lines: Iterable[str]) -> dict[str, Counter[str]]:
    """Greek letters as symbols in Latin text (``symbols``, μ included), μ alone (``mu``), and
    Greek-language letters (``language``), by the line rule."""
    out: dict[str, Counter[str]] = {"symbols": Counter(), "mu": Counter(), "language": Counter()}
    for line in lines:
        line = norm(line)
        language = bool(GREEK_RUN.search(line))
        for ch in line:
            if ch not in GREEK:
                continue
            if language:
                out["language"][ch] += 1
            else:
                out["symbols"][ch] += 1
                if ch == MU:
                    out["mu"][ch] += 1
    return out


def greek_compare(ref_lines: Iterable[str], out_lines: Iterable[str]) -> dict[str, int]:
    ref, out = greek_split(ref_lines), greek_split(out_lines)
    res = {}
    for key in ("symbols", "mu", "language"):
        res[f"{key}_held"] = held(ref[key], out[key])
        res[f"{key}_of"] = sum(ref[key].values())
    ref_all = ref["symbols"] + ref["language"]
    out_all = out["symbols"] + out["language"]
    res["returned_not_in_layer"] = sum(out_all.values()) - held(out_all, ref_all)
    return res


# ── numbers in tables ────────────────────────────────────────────────────────


def number_compare(layer_text: str, cell_texts: Iterable[str]) -> dict[str, int]:
    """Numbers of the layer inside a table's box against the numbers of its cells."""
    cells = [norm(t) for t in cell_texts]
    layer = Counter(NUMBER.findall(norm(layer_text)))
    out = Counter(n for t in cells for n in NUMBER.findall(strip_marks(t)))
    flattened = 0
    for t in cells:
        for number, mark in MARKED_NUMBER.findall(t):
            joined = number + mark
            if layer[joined] > 0 and out[number] > 0 and layer[number] <= out[number] - 1:
                layer[joined] -= 1
                out[number] -= 1
                flattened += 1
    h = held(layer, out)
    return {"layer_numbers": sum(layer.values()), "layer_held_by_cells": h,
            "cell_numbers": sum(out.values()), "cells_held_by_layer": held(out, layer),
            "flattened_mark_pairs": flattened}


# ── a document against its PDF ───────────────────────────────────────────────


def _resolve(doc: dict[str, Any], ref: str) -> dict[str, Any]:
    _, kind, idx = ref.split("/")
    return doc[kind][int(idx)]


def _box(prov: dict[str, Any], height: float) -> tuple[float, float, float, float]:
    """Docling's bounding box as (x0, y0, x1, y1) with the origin at the top left, as pymupdf."""
    b = prov["bbox"]
    if b.get("coord_origin", "BOTTOMLEFT") == "BOTTOMLEFT":
        return b["l"], height - b["t"], b["r"], height - b["b"]
    return b["l"], b["t"], b["r"], b["b"]


def _inside(word: tuple[Any, ...], box: tuple[float, float, float, float]) -> bool:
    cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _lines(words: list[tuple[Any, ...]]) -> list[str]:
    grouped: dict[tuple[int, int], list[str]] = {}
    for w in words:
        grouped.setdefault((w[5], w[6]), []).append(w[4])
    return [" ".join(ws) for ws in grouped.values()]


def doc_texts(doc: dict[str, Any]) -> list[str]:
    """Every text of the document: text items (body and furniture) and table cells, marks removed."""
    out = [t.get("text", "") for t in doc.get("texts", [])]
    out += [strip_marks(c.get("text", "")) for t in doc.get("tables", []) for c in t["data"]["table_cells"]]
    return out


def compare_with_layer(doc: dict[str, Any], pdf: Any) -> dict[str, Any]:
    """Table numbers and Greek letters of one parsed document against its PDF's text layer."""
    heights = {int(k): v["size"]["height"] for k, v in doc.get("pages", {}).items()}
    boxes: dict[int, list[tuple[int, tuple[float, float, float, float]]]] = {}
    for i, table in enumerate(doc.get("tables", [])):
        for prov in table.get("prov", []):
            page = prov["page_no"]
            boxes.setdefault(page, []).append((i, _box(prov, heights.get(page, pdf[page - 1].rect.height))))
    table_layer: dict[int, list[tuple[Any, ...]]] = {}
    tables_without_layer: set[int] = set()
    page_ref: list[str] = []
    page_out: list[str] = []
    for page_no in range(1, pdf.page_count + 1):
        page = pdf[page_no - 1]
        if len(page.get_text("text").strip()) < NO_TEXT_CHARS:
            tables_without_layer |= {i for i, _ in boxes.get(page_no, [])}
            continue
        words = page.get_text("words")
        outside = []
        for w in words:
            hit = [i for i, box in boxes.get(page_no, []) if _inside(w, box)]
            for i in hit:
                table_layer.setdefault(i, []).append(w)
            if not hit:
                outside.append(w)
        page_ref += _lines(outside)
        page_out += [t.get("text", "") for t in doc.get("texts", [])
                     if any(p["page_no"] == page_no for p in t.get("prov", []))]
    tables = []
    for i, table in enumerate(doc.get("tables", [])):
        if i in tables_without_layer or i not in table_layer:
            continue
        cells = [c.get("text", "") for c in table["data"]["table_cells"]]
        lines = _lines(table_layer[i])
        tables.append({"table": i, **number_compare(" ".join(lines), cells),
                       **{f"greek_{k}": v for k, v in greek_compare(lines, cells).items()}})
    return {"tables": tables, "tables_on_pages_without_layer": len(tables_without_layer),
            "page_text_greek": greek_compare(page_ref, page_out)}


# ── the batch ────────────────────────────────────────────────────────────────


def _pages_with_tables(doc: dict[str, Any]) -> int:
    return len({p["page_no"] for t in doc.get("tables", []) for p in t.get("prov", [])})


def collect(items: list[dict[str, Any]], root: Path, opts_hash: str,
            legacy: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """One record per listed document: its parse, sizes and comparisons, or its failure."""
    import pymupdf

    failures: dict[str, str] = {}
    fpath = root / FAILURES_FILE
    if fpath.exists():
        for line in fpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                f = json.loads(line)
                failures[f["url"]] = f["error"]
    out = []
    for item in items:
        url = item["url"]
        rec: dict[str, Any] = {"url": url, "group": item.get("group", "")}
        try:
            pdf_bytes = read_pdf(item.get("cache_path"))
        except Exception as exc:  # noqa: BLE001
            out.append({**rec, "status": "failed", "error": failures.get(url, f"read: {exc}")})
            continue
        folder = parse_folder(root, doc_id_for(url, pdf_bytes), opts_hash)
        if not (folder / RUN_FILE).exists():
            status = "failed" if url in failures else "not parsed"
            out.append({**rec, "status": status, "error": failures.get(url, "")})
            continue
        run = json.loads((folder / RUN_FILE).read_text())
        doc = json.loads((folder / DOC_FILE).read_text())
        sizes = {}
        for name in (RAW_FILE, DOC_FILE, RUN_FILE):
            data = (folder / name).read_bytes()
            sizes[name] = {"plain": len(data), "gzip": len(gzip.compress(data, compresslevel=6))}
        counts = run["counts"]
        texts = doc_texts(doc)
        rec.update(status="parsed", seconds=run["seconds"], pages=counts["pages"], tables=counts["tables"],
                   cells=counts["cells"], pages_without_tables=counts["pages"] - _pages_with_tables(doc),
                   post={k: counts.get(k, 0) for k in POST_COUNTS}, sizes=sizes,
                   cjk=sum(len(CJK.findall(t)) for t in texts), recovered=url in failures)
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            rec["layer"] = compare_with_layer(doc, pdf)
        if legacy is not None and url in legacy:
            ref = norm(legacy[url])
            got = norm("\n".join(texts))
            rw, gw = Counter(WORD.findall(ref)), Counter(WORD.findall(got))
            rn, gn = Counter(NUMBER.findall(ref)), Counter(NUMBER.findall(got))
            rec["legacy"] = {"words_held": held(rw, gw), "words_of": sum(rw.values()),
                             "numbers_held": held(rn, gn), "numbers_of": sum(rn.values())}
        out.append(rec)
    return out


def rates(recs: list[dict[str, Any]]) -> dict[str, Any]:
    import numpy as np

    parsed = [r for r in recs if r["status"] == "parsed"]
    plain = [r for r in parsed if r["tables"] == 0]
    res: dict[str, Any] = {
        "n": len(parsed), "pages": sum(r["pages"] for r in parsed),
        "seconds": round(sum(r["seconds"] for r in parsed), 1),
        "seconds_per_page_all": share(sum(r["seconds"] for r in parsed), sum(r["pages"] for r in parsed)),
        "docs_without_tables": len(plain),
        "seconds_per_page_without_tables": share(sum(r["seconds"] for r in plain), sum(r["pages"] for r in plain)),
        "fit": None,
    }
    if len(parsed) >= 3:
        x = np.array([[r["pages_without_tables"], r["tables"], r["cells"]] for r in parsed], dtype=float)
        y = np.array([r["seconds"] for r in parsed], dtype=float)
        coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        res["fit"] = {"per_page_without_tables": round(float(coef[0]), 3), "per_table": round(float(coef[1]), 3),
                      "per_cell": round(float(coef[2]), 4), "n": len(parsed)}
    return res


def _sum(dicts: Iterable[dict[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for d in dicts:
        total.update(d)
    return dict(total)


def summarise(recs: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = [r for r in recs if r["status"] == "parsed"]
    pages = sum(r["pages"] for r in parsed)
    sizes = {}
    for name in (RAW_FILE, DOC_FILE, RUN_FILE):
        sizes[name] = {k: round(sum(r["sizes"][name][k] for r in parsed) / pages) if pages else None
                       for k in ("plain", "gzip")}
    tables = [t for r in parsed for t in r["layer"]["tables"]]
    tnum = _sum({k: t[k] for k in ("layer_numbers", "layer_held_by_cells", "cell_numbers", "cells_held_by_layer",
                                   "flattened_mark_pairs")} for t in tables)
    tgreek = _sum({k[6:]: v for k, v in t.items() if k.startswith("greek_")} for t in tables)
    pgreek = _sum(r["layer"]["page_text_greek"] for r in parsed)
    legacy = _sum(r["legacy"] for r in parsed if "legacy" in r)
    return {
        "listed": len(recs), "parsed": len(parsed),
        "failed": [{"url": r["url"], "group": r["group"], "error": r["error"]} for r in recs if r["status"] == "failed"],
        "not_parsed": sum(1 for r in recs if r["status"] == "not parsed"),
        "recovered_after_failure": sum(1 for r in parsed if r["recovered"]),
        "rates": {g: rates([r for r in recs if r["group"] == g]) for g in sorted({r["group"] for r in recs})},
        "bytes_per_page": sizes,
        "post_processing": _sum(r["post"] for r in parsed),
        "table_numbers": {**tnum, "tables_checked": len(tables),
                          "tables_on_pages_without_layer": sum(r["layer"]["tables_on_pages_without_layer"] for r in parsed),
                          "layer_share": share(tnum.get("layer_held_by_cells", 0), tnum.get("layer_numbers", 0)),
                          "cell_share": share(tnum.get("cells_held_by_layer", 0), tnum.get("cell_numbers", 0))},
        "greek_tables": tgreek, "greek_page_text": pgreek,
        "cjk": {"total": sum(r["cjk"] for r in parsed),
                "documents": [{"url": r["url"], "cjk": r["cjk"]} for r in parsed if r["cjk"]]},
        "legacy": {**legacy, "n": sum(1 for r in parsed if "legacy" in r),
                   "words_share": share(legacy.get("words_held", 0), legacy.get("words_of", 0)),
                   "numbers_share": share(legacy.get("numbers_held", 0), legacy.get("numbers_of", 0))},
    }


def _pct(h: int | None, n: int | None) -> str:
    return f"{h} of {n} ({100 * h / n:.1f}%)" if n else "n = 0"


def render(s: dict[str, Any], title: str) -> str:
    out = [f"# {title}", "", f"Listed {s['listed']}, parsed {s['parsed']}, failed {len(s['failed'])}, "
           f"not parsed {s['not_parsed']}, parsed after an earlier failure {s['recovered_after_failure']}.", "",
           "## Rates", "", "| Group | n | Pages | Seconds | s/page, all | s/page, documents without tables (n) | Fit: s/page without tables | s/table | s/cell |",
           "|---|---|---|---|---|---|---|---|---|"]
    for g, r in s["rates"].items():
        fit = r["fit"] or {}
        out.append(f"| {g or '—'} | {r['n']} | {r['pages']} | {r['seconds']} | {r['seconds_per_page_all']} | "
                   f"{r['seconds_per_page_without_tables'] or '—'} ({r['docs_without_tables']}) | "
                   f"{fit.get('per_page_without_tables', '—')} | {fit.get('per_table', '—')} | {fit.get('per_cell', '—')} |")
    out += ["", "The fit is least squares without intercept, over the group's parsed documents (n ≥ 3).", "",
            "## Failures", ""]
    out += [f"- {f['url']} ({f['group']}): {f['error']}" for f in s["failed"]] or ["None."]
    out += ["", "## Bytes per page", "", "| File | Plain | Gzip |", "|---|---|---|"]
    out += [f"| `{k}` | {v['plain']} | {v['gzip']} |" for k, v in s["bytes_per_page"].items()]
    out += ["", "## Post-processing", "", "| Count | Value |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in s["post_processing"].items()]
    t = s["table_numbers"]
    out += ["", "## Table numbers against the text layer", "",
            f"Tables checked: {t['tables_checked']}; on pages without a text layer: {t['tables_on_pages_without_layer']}.", "",
            f"- Layer numbers inside the tables' boxes held by the cells: {_pct(t.get('layer_held_by_cells', 0), t.get('layer_numbers', 0))}",
            f"- Cell numbers held by the layer: {_pct(t.get('cells_held_by_layer', 0), t.get('cell_numbers', 0))}",
            f"- Pairs where the layer flattened a footnote mark (layer 12.51, cell 12.5[^1]), left out of both shares: {t.get('flattened_mark_pairs', 0)}",
            "", "The check cannot see a number in the wrong cell.", "",
            "## Greek letters and the micro sign against the text layer", "",
            "Line rule: a Greek letter on a line without a run of 3 or more Greek letters is a symbol in Latin text; "
            "the others are Greek-language letters. A line is a text line of the layer, a text item of Docling's page text, "
            "and a cell of a table. Texts are NFKC-normalised, so µ and μ are one sign.", "",
            "| Where | Greek symbols in Latin text | of which μ | Greek-language letters | Greek letters returned that the layer lacks |",
            "|---|---|---|---|---|"]
    for where, g in (("page text", s["greek_page_text"]), ("tables", s["greek_tables"])):
        out.append(f"| {where} | {_pct(g.get('symbols_held', 0), g.get('symbols_of', 0))} | {_pct(g.get('mu_held', 0), g.get('mu_of', 0))} | "
                   f"{_pct(g.get('language_held', 0), g.get('language_of', 0))} | {g.get('returned_not_in_layer', 0)} |")
    c = s["cjk"]
    out += ["", "## CJK characters", "", f"Total {c['total']} in {len(c['documents'])} documents."]
    out += [f"- {d['url']}: {d['cjk']}" for d in c["documents"]]
    lg = s["legacy"]
    out += ["", "## Against the legacy text of the same documents", "",
            f"n = {lg['n']}. Words held: {_pct(lg.get('words_held', 0), lg.get('words_of', 0))}. "
            f"Numbers held: {_pct(lg.get('numbers_held', 0), lg.get('numbers_of', 0))}.", ""]
    return "\n".join(out)


def legacy_texts(urls: list[str]) -> dict[str, str]:
    from pymongo import MongoClient

    col = MongoClient(config.MONGO_URI)[config.MONGO_DB]["parsed_documents"]
    return {r["url"]: r.get("text") or "" for r in col.find({**LEGACY_QUERY, "url": {"$in": urls}}, {"url": 1, "text": 1})}


def main(argv: list[str] | None = None) -> int:
    from corpus.parsers.docling_pdf import OPTIONS_HASH

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("list", type=Path)
    ap.add_argument("--root", type=Path, default=config.PARSED_ROOT)
    ap.add_argument("--out-dir", type=Path, default=config.RESULTS_DIR / "docling")
    ap.add_argument("--no-legacy", action="store_true", help="skip the comparison with the legacy text")
    args = ap.parse_args(argv)
    items = load_items(args.list)
    legacy = None if args.no_legacy else legacy_texts([i["url"] for i in items])
    recs = collect(items, args.root, OPTIONS_HASH, legacy)
    summary = summarise(recs)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"report_{args.list.stem}"
    (args.out_dir / f"{stem}.json").write_text(json.dumps({"summary": summary, "documents": recs}, ensure_ascii=False, indent=1))
    (args.out_dir / f"{stem}.md").write_text(render(summary, f"Docling batch report: {args.list.name}"))
    print(json.dumps({"out": str(args.out_dir / f"{stem}.md"), "parsed": summary["parsed"], "failed": len(summary["failed"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
