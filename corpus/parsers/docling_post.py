"""Post-processing of a stored Docling document (backlog row 17).

Plain Python on the JSON dict of ``doc.raw.json`` (Docling's ``export_to_dict``): no Docling
import, so .venv and the gate run it. :func:`post_process` returns a new dict for ``doc.json``
and the counts of what it changed; the input is never modified, so a rule can be improved
and applied again without a new parse.

Rule 1, tables over pages: a table that continues on the next page comes out of the parse
as one table per page. PaddleOCR-VL kept 6 columns on each of the four pages of one EMA
procedural-steps table, as four separate tables. The parts are joined into one table that
keeps one provenance entry per page.
"""

from __future__ import annotations

import copy
import re
from typing import Any

_TABLE_REF = re.compile(r"^#/tables/(\d+)$")


def _resolve(doc: dict[str, Any], ref: str) -> dict[str, Any]:
    _, kind, idx = ref.split("/")
    return doc[kind][int(idx)]


def _reading_order(doc: dict[str, Any]) -> list[str]:
    """The refs of the body in reading order, depth first through groups."""
    order: list[str] = []
    stack = [c["$ref"] for c in reversed(doc["body"].get("children", []))]
    while stack:
        ref = stack.pop()
        order.append(ref)
        if ref.startswith("#/groups/"):
            stack.extend(c["$ref"] for c in reversed(_resolve(doc, ref).get("children", [])))
    return order


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _rows(table: dict[str, Any]) -> list[list[str]]:
    data = table["data"]
    rows = [[""] * data["num_cols"] for _ in range(data["num_rows"])]
    for c in data["table_cells"]:
        if c["start_row_offset_idx"] < data["num_rows"] and c["start_col_offset_idx"] < data["num_cols"]:
            rows[c["start_row_offset_idx"]][c["start_col_offset_idx"]] = _norm(c.get("text", ""))
    return rows


def _rebuild_grid(data: dict[str, Any]) -> None:
    grid: list[list[dict[str, Any] | None]] = [[None] * data["num_cols"] for _ in range(data["num_rows"])]
    for c in data["table_cells"]:
        for r in range(c["start_row_offset_idx"], min(c["end_row_offset_idx"], data["num_rows"])):
            for col in range(c["start_col_offset_idx"], min(c["end_col_offset_idx"], data["num_cols"])):
                grid[r][col] = c
    data["grid"] = [[cell if cell is not None else {} for cell in row] for row in grid]


def _append_part(first: dict[str, Any], part: dict[str, Any]) -> None:
    """Append ``part``'s rows to ``first``, dropping leading rows that repeat its header."""
    head, rows = _rows(first), _rows(part)
    repeat = 0
    while repeat < min(len(head), len(rows)) and rows[repeat] == head[repeat] and any(rows[repeat]):
        repeat += 1
    offset = first["data"]["num_rows"] - repeat
    for c in part["data"]["table_cells"]:
        if c["start_row_offset_idx"] < repeat:
            continue
        cell = dict(c)
        cell["start_row_offset_idx"] += offset
        cell["end_row_offset_idx"] += offset
        first["data"]["table_cells"].append(cell)
    first["data"]["num_rows"] += part["data"]["num_rows"] - repeat
    first["prov"].extend(part["prov"])
    for key in ("footnotes", "references", "children"):
        first[key] = first.get(key, []) + part.get(key, [])


def join_tables_over_pages(doc: dict[str, Any]) -> int:
    """Rule 1, in place on ``doc``. Returns the number of joins.

    Part B continues table A when, in reading order, nothing but page headers and footers
    (``content_layer: furniture``), A's own captions and footnotes, and pictures on A's last
    page (the agency's logo sits there on EMA's first pages) lies between them; B
    starts on the page after A's last page; both have the same label and column count; and
    B has no caption. One pass over the reading order: the cost grows with the number of
    elements, not with joins times elements.
    """
    tables = doc.get("tables", [])
    if len(tables) < 2:
        return 0
    joined_into: dict[int, int] = {}  # index of a removed part -> index of its table
    current: int | None = None  # the table that a continuation would join
    allowed: set[str] = set()
    for ref in _reading_order(doc):
        m = _TABLE_REF.match(ref)
        if m:
            idx = int(m.group(1))
            part = tables[idx]
            if current is not None:
                first = tables[current]
                if (part["prov"] and first["prov"]
                        and part["prov"][0]["page_no"] == first["prov"][-1]["page_no"] + 1
                        and part.get("label") == first.get("label")
                        and part["data"]["num_cols"] == first["data"]["num_cols"]
                        and not part.get("captions")):
                    _append_part(first, part)
                    joined_into[idx] = current
                    allowed |= {r["$ref"] for r in part.get("footnotes", [])}
                    continue
            current = idx
            allowed = {r["$ref"] for k in ("captions", "footnotes") for r in part.get(k, [])}
            continue
        if current is None:
            continue
        item = _resolve(doc, ref)
        if item.get("content_layer") == "furniture" or ref in allowed:
            continue
        last_page = tables[current]["prov"][-1]["page_no"] if tables[current]["prov"] else None
        if item.get("label") == "picture" and item.get("prov") and all(
            pr["page_no"] == last_page for pr in item["prov"]
        ):
            continue  # a logo or decoration on the table's last page does not end the table
        current = None
    if joined_into:
        _remove_tables(doc, joined_into)
    return len(joined_into)


def _remove_tables(doc: dict[str, Any], joined_into: dict[int, int]) -> None:
    """Drop the joined parts and renumber every ``#/tables/N`` reference once."""
    keep = [i for i in range(len(doc["tables"])) if i not in joined_into]
    new_index = {old: new for new, old in enumerate(keep)}
    for old, target in joined_into.items():
        new_index[old] = new_index[target]
    doc["tables"] = [doc["tables"][i] for i in keep]
    removed = {f"#/tables/{i}" for i in joined_into}

    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            if set(node) == {"$ref"}:
                m = _TABLE_REF.match(node["$ref"])
                if m:
                    return {"$ref": f"#/tables/{new_index[int(m.group(1))]}"}
                return node
            out = {}
            for k, v in node.items():
                if k == "children" and isinstance(v, list):
                    v = [c for c in v if not (isinstance(c, dict) and c.get("$ref") in removed)]
                out[k] = fix(v)
            return out
        if isinstance(node, list):
            return [fix(v) for v in node]
        if isinstance(node, str):
            m = _TABLE_REF.match(node)
            return f"#/tables/{new_index[int(m.group(1))]}" if m else node
        return node

    fixed = fix(doc)
    doc.clear()
    doc.update(fixed)
    for i, t in enumerate(doc["tables"]):
        t["self_ref"] = f"#/tables/{i}"
        _rebuild_grid(t["data"])


def post_process(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """All rules, in order, on a copy of ``raw``. Returns the new document and the counts."""
    doc = copy.deepcopy(raw)
    counts = {"tables_joined": join_tables_over_pages(doc)}
    return doc, counts
