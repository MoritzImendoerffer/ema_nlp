"""Post-processing of a stored Docling document (backlog row 17).

Plain Python on the JSON dict of ``doc.raw.json`` (Docling's ``export_to_dict``): no Docling
import, so .venv and the gate run it. :func:`post_process` returns a new dict for ``doc.json``
and the counts of what it changed; the input is never modified, so a rule can be improved
and applied again without a new parse.

Rule 1, tables over pages: a table that continues on the next page comes out of the parse
as one table per page. PaddleOCR-VL kept 6 columns on each of the four pages of one EMA
procedural-steps table, as four separate tables. The parts are joined into one table that
keeps one provenance entry per page.

Rule 2, footnotes in tables: PaddleOCR-VL writes a footnote mark as superscript markup,
``12.5\\(^{1}\\)``. Read as plain text that becomes "12.51", another number. The mark is
written as a Unicode superscript, "12.5¹", so it stays a mark. Footnote texts below a table
that begin with a mark used in its cells are attached to that table.

Rule 3, the model's markup: some cell text comes back as LaTeX, such as ``\\(\\pm\\)``,
``2.06e^{-14}``, ``\\alpha``, ``\\text{...}`` or a literal ``\\n``. It is turned into text.
Greek letters are kept as Greek letters: they carry meaning in EMA tables (α-tocopherol, Δ,
μg). Dashes are left as the parser wrote them: a guess at the original character is worse
than a known substitution.

Rule 4, the reference number from the page header: Docling keeps page headers apart from the
body, and its Markdown export leaves them out. An EMA document's reference number
(``EMA/CHMP/123456/2020``) often stands only in the page header, and the build reads it from
the first 2,048 characters of the row's text (``corpus/metadata/text_metadata.py``). When the
body does not hold it there, the first page header that does is copied into the body as its
first item.
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


_SUPERSCRIPT = dict(zip("0123456789+-=()abcdefghijklmnoprstuvwxyz",
                        "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"))
_BASE = {v: k for k, v in _SUPERSCRIPT.items()}
# A superscript after a mantissa (2.06e^{-14}, 10^{3}) is an exponent, not a footnote mark;
# rule 3 writes it as text.
_EXPONENT_BEFORE = re.compile(r"(?:\d[eE]|10)$")
_SUP_MARKUP = re.compile(r"\\\(\s*\^\{([^{}]{1,4})\}\s*\\\)|\^\{([^{}]{1,4})\}")
_TRAILING_MARKS = re.compile(r"([⁰¹²³⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ*†‡§]+)$")
_FOOTNOTE_START = re.compile(r"^\s*(?:\(?([0-9]{1,2}|[a-z]|\*{1,3}|[†‡§])\)?(?=[\s.:)])|([⁰¹²³⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ]+))")


def superscript_marks(text: str) -> tuple[str, int]:
    """Write ``\\(^{1}\\)`` and ``^{a}`` as Unicode superscripts; leave exponents for rule 3.

    Returns the new text and the number of marks written. A mark without a Unicode
    superscript form stays as ``^x``, still apart from the number before it.
    """
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        mark = (m.group(1) or m.group(2) or "").strip()
        if _EXPONENT_BEFORE.search(text[: m.start()]):
            return m.group(0)
        count += 1
        if mark and all(ch.lower() in _SUPERSCRIPT for ch in mark):
            return "".join(_SUPERSCRIPT[ch.lower()] for ch in mark)
        return "^" + mark

    return _SUP_MARKUP.sub(repl, text), count


def _base_mark(mark: str) -> str:
    return "".join(_BASE.get(ch, ch) for ch in mark)


def attach_table_footnotes(doc: dict[str, Any]) -> tuple[int, int]:
    """Rule 2, in place. Returns (marks written as superscripts, footnote texts attached)."""
    marks_written = attached = 0
    marks_by_table: dict[int, set[str]] = {}
    for i, table in enumerate(doc.get("tables", [])):
        marks: set[str] = set()
        for cell in table["data"]["table_cells"]:
            text, n = superscript_marks(cell.get("text", ""))
            cell["text"] = text
            marks_written += n
            m = _TRAILING_MARKS.search(text.strip())
            if m:
                marks |= {_base_mark(ch) for ch in m.group(1)}
        marks_by_table[i] = marks
        _rebuild_grid(table["data"])
    body = doc["body"]["children"]
    out_children: list[dict[str, str]] = []
    current: int | None = None
    for child in body:
        ref = child["$ref"]
        tm = _TABLE_REF.match(ref)
        if tm:
            current = int(tm.group(1))
            out_children.append(child)
            continue
        if current is not None and ref.startswith("#/texts/"):
            item = _resolve(doc, ref)
            if item.get("content_layer") == "furniture":
                out_children.append(child)
                continue
            fm = _FOOTNOTE_START.match(item.get("text", ""))
            mark = _base_mark(fm.group(1) or fm.group(2) or "") if fm else ""
            if mark and mark in marks_by_table.get(current, set()):
                table = doc["tables"][current]
                item["parent"] = {"$ref": f"#/tables/{current}"}
                table.setdefault("footnotes", []).append({"$ref": ref})
                table.setdefault("children", []).append({"$ref": ref})
                attached += 1
                continue
        current = None if not tm else current
        out_children.append(child)
    doc["body"]["children"] = out_children
    return marks_written, attached


_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π", "varpi": "ϖ",
    "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ", "Epsilon": "Ε", "Zeta": "Ζ",
    "Eta": "Η", "Theta": "Θ", "Iota": "Ι", "Kappa": "Κ", "Lambda": "Λ", "Mu": "Μ", "Nu": "Ν",
    "Xi": "Ξ", "Omicron": "Ο", "Pi": "Π", "Rho": "Ρ", "Sigma": "Σ", "Tau": "Τ",
    "Upsilon": "Υ", "Phi": "Φ", "Chi": "Χ", "Psi": "Ψ", "Omega": "Ω",
}
_SYMBOLS = {
    "pm": "±", "mp": "∓", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "times": "×",
    "cdot": "·", "div": "÷", "neq": "≠", "ne": "≠", "approx": "≈", "sim": "~", "simeq": "≃",
    "infty": "∞", "rightarrow": "→", "to": "→", "leftarrow": "←", "uparrow": "↑",
    "downarrow": "↓", "degree": "°", "circ": "°", "prime": "′", "%": "%", "log": "log",
    "ln": "ln", "lt": "<", "gt": ">", "ll": "≪", "gg": "≫", "dagger": "†", "ddagger": "‡",
    "S": "§", "quad": " ", "qquad": " ", ",": " ", ";": " ", "!": "",
}
_WRAPPERS = re.compile(r"\\(?:text|mathrm|textrm|mathit|textit|mathbf|textbf|operatorname)\{([^{}]*)\}")
_DEGREE = re.compile(r"\^\{\s*\\circ\s*\}")
_EXPONENT = re.compile(r"(\d[eE]|10)\^\{([+-]?\d{1,3})\}")
_SUBSCRIPT_MARKUP = re.compile(r"_\{([^{}]{1,6})\}")
_COMMAND = re.compile(r"\\([A-Za-z]+|[%,;!])( +(?=[A-Za-z]))?")


def convert_markup(text: str) -> tuple[str, int]:
    """Rule 3 on one cell's text. Returns the text and the number of conversions."""
    count = 0

    def sub(rx: re.Pattern[str], repl: Any, value: str) -> str:
        nonlocal count
        new, n = rx.subn(repl, value)
        count += n
        return new

    t = sub(_WRAPPERS, lambda m: m.group(1), text)
    t = sub(_DEGREE, "°", t)
    t = sub(_EXPONENT, lambda m: f"{m.group(1)}{m.group(2)}" if m.group(1) != "10" else f"10^{m.group(2)}", t)
    # A subscript becomes plain text: the PDF's text layer writes C_max as "Cmax", and a
    # search for "Cmax" must find the cell.
    t = sub(_SUBSCRIPT_MARKUP, lambda m: m.group(1), t)

    def command(m: re.Match[str]) -> str:
        nonlocal count
        name = m.group(1)
        if name in _GREEK:
            count += 1
            return _GREEK[name]
        if name in _SYMBOLS:
            count += 1
            return _SYMBOLS[name]
        return m.group(0)  # unknown command: left as written, never guessed

    # Known commands first, matched as a whole word: \\nu is ν and \\neq is ≠. A literal \\n
    # (a line break inside a cell) is replaced only after that, so "Pharma\\nceutical"
    # becomes "Pharma ceutical" and not a command.
    t = _COMMAND.sub(command, t)
    if "\\n" in t:
        count += t.count("\\n")
        t = t.replace("\\n", " ")
    for delim in ("\\(", "\\)", "\\[", "\\]"):
        if delim in t:
            count += t.count(delim)
            t = t.replace(delim, "")
    t = re.sub(r"\$([^$]{1,40})\$", lambda m: m.group(1), t)
    return " ".join(t.split()) if t != text else t, count


def convert_table_markup(doc: dict[str, Any]) -> int:
    """Rule 3, in place on every table cell. Returns the number of conversions."""
    total = 0
    for table in doc.get("tables", []):
        for cell in table["data"]["table_cells"]:
            cell["text"], n = convert_markup(cell.get("text", ""))
            total += n
        _rebuild_grid(table["data"])
    return total


def _body_text(doc: dict[str, Any], limit: int = 2048) -> str:
    """The text of the body's text items in reading order, up to ``limit`` characters."""
    parts: list[str] = []
    size = 0
    for ref in _reading_order(doc):
        if not ref.startswith("#/texts/"):
            continue
        item = _resolve(doc, ref)
        if item.get("content_layer") == "furniture":
            continue
        parts.append(item.get("text", ""))
        size += len(parts[-1]) + 1
        if size >= limit:
            break
    return " ".join(parts)[:limit]


def lift_header_reference(doc: dict[str, Any]) -> int:
    """Rule 4, in place. Returns 1 when a page header was copied into the body, else 0."""
    from corpus.metadata.text_metadata import EMA_REF_RE

    if EMA_REF_RE.search(_body_text(doc)):
        return 0
    headers = [t for t in doc.get("texts", [])
               if t.get("label") == "page_header" and EMA_REF_RE.search(t.get("text", ""))]
    if not headers:
        return 0
    first = min(headers, key=lambda t: (t["prov"][0]["page_no"] if t.get("prov") else 10**6))
    item = copy.deepcopy(first)
    item.update({"self_ref": f"#/texts/{len(doc['texts'])}", "parent": {"$ref": "#/body"},
                 "children": [], "content_layer": "body", "label": "text"})
    doc["texts"].append(item)
    doc["body"]["children"].insert(0, {"$ref": item["self_ref"]})
    return 1


def post_process(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """All rules, in order, on a copy of ``raw``. Returns the new document and the counts."""
    doc = copy.deepcopy(raw)
    counts = {"tables_joined": join_tables_over_pages(doc)}
    counts["footnote_marks"], counts["footnotes_attached"] = attach_table_footnotes(doc)
    counts["markup_converted"] = convert_table_markup(doc)
    counts["header_reference_lifted"] = lift_header_reference(doc)
    return doc, counts
