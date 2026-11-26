"""The ``docling`` PDF parser (backlog row 17): Docling with PaddleOCR models.

The pipeline, fixed by the exploration of work unit 28:

- Docling 2.153.0's standard PDF pipeline; text from the PDF's text layer where one exists.
- Layout: the Heron model at a pinned revision. Docling would request its newest revision.
- OCR, for regions without a text layer only: RapidOCR with the multilingual PP-OCRv6 small
  detector and the PP-OCRv6 **medium** recognizer. On 30 pages with a known answer it held
  92.6% of words, 98.2% of numbers and 95.5% of µ signs; the English PP-OCRv5 model lost words
  and × signs. Setting ``lang=["en"]`` alone changes nothing: it loads the same multilingual
  model. Docling's ``model_size`` switches detector and recognizer together, so the recognizer
  is given by path; its character list equals the small model's.
- Tables: PaddleOCR-VL-1.6 on every table (``corpus/parsers/paddleocr_vl_table.py``).

Docling, torch and the models live in the parse environment (``make parse-env``), never in
.venv. In .venv, :meth:`DoclingPdfParser.parse` returns an error that starts with
``missing_extra``, and the module imports nothing heavy at import time.
"""

from __future__ import annotations

import gzip
import hashlib
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from corpus.parsers.base import ParsedDocument
from corpus.parsers.docling_store import PARSER_NAME, options_hash, parser_version

HERON_REPO = "docling-project/docling-layout-heron"
HERON_REVISION = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
# The PP-OCRv6 medium recognizer, as rapidocr 3.10.0's default_models.yaml lists it.
REC_MEDIUM_URL = (
    "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_medium.onnx"
)
REC_MEDIUM_SHA256 = "eef444829dbbe18d7fea59a3f6eb75647518d2b3a9568d27c92e42940204894b"
GZIP_MAGIC = b"\x1f\x8b"

# Everything that changes the parse. Its hash names the folder and the row's version.
OPTIONS: dict[str, Any] = {
    "pipeline": "docling-standard-pdf",
    "layout": {"model": HERON_REPO, "revision": HERON_REVISION},
    "ocr": {"engine": "rapidocr", "backend": "onnxruntime", "detector": "PP-OCRv6 small",
            "recognizer": "PP-OCRv6 medium", "recognizer_sha256": REC_MEDIUM_SHA256,
            "mode": "regions without a text layer"},
    "tables": {"stage": "ema_paddleocr_vl", "model": "PaddlePaddle/PaddleOCR-VL-1.6",
               "revision": "c5630abae1d940eafe0697512a0325494b02ab42", "dpi": 200},
}
OPTIONS_HASH = options_hash(OPTIONS)


def models_dir() -> Path:
    import config

    return Path(config.DOCLING_ENV) / "models"


def rec_model_path() -> Path:
    return models_dir() / "PP-OCRv6_rec_medium.onnx"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_rec_model() -> Path:
    """Download the medium recognizer once and check its SHA-256. A batch never downloads."""
    path = rec_model_path()
    if path.exists() and _sha256(path) == REC_MEDIUM_SHA256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(REC_MEDIUM_URL, tmp)  # noqa: S310 (fixed https URL)
    if _sha256(tmp) != REC_MEDIUM_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {REC_MEDIUM_URL}")
    tmp.replace(path)
    return path


@lru_cache(maxsize=1)
def build_converter() -> Any:
    """Docling's converter with the options above. Imports Docling; parse environment only."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        LayoutObjectDetectionOptions,
        PdfPipelineOptions,
        RapidOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from corpus.parsers.paddleocr_vl_table import PaddleOcrVlTableOptions, register

    register()
    layout = LayoutObjectDetectionOptions.from_preset("layout_heron_default")
    layout = layout.model_copy(update={"model_spec": layout.model_spec.model_copy(update={"revision": HERON_REVISION})})
    rec = rec_model_path()
    if not rec.exists():
        raise FileNotFoundError(f"{rec} is missing: run the parser's prefetch (make parse-env)")
    opts = PdfPipelineOptions(
        allow_external_plugins=True,
        do_ocr=True,
        ocr_options=RapidOcrOptions(backend="onnxruntime", model_size="small", rec_model_path=str(rec)),
        table_structure_options=PaddleOcrVlTableOptions(),
        layout_options=layout,
    )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def prefetch() -> Path:
    """Fetch the recognizer and build the converter once, so every model is on disk."""
    path = fetch_rec_model()
    build_converter()
    return path


def docling_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("docling")
    except PackageNotFoundError:
        return "missing"


@dataclass
class Conversion:
    """The outcome of one PDF: Docling's document as a dict, or the error."""

    status: str
    error: str = ""
    document: dict[str, Any] | None = None
    markdown: str = ""
    pages: int = 0
    seconds: float = 0.0
    counts: dict[str, int] = field(default_factory=dict)


def pdf_page_count(raw: bytes) -> int:
    """Pages of a PDF, read with pypdfium2 (Docling's own PDF library)."""
    import pypdfium2

    pdf = pypdfium2.PdfDocument(raw)
    try:
        return len(pdf)
    finally:
        pdf.close()


def page_ranges(pages: int, range_pages: int) -> list[tuple[int, int] | None]:
    """``[None]`` for one pass; else 1-based inclusive ranges of at most ``range_pages`` pages."""
    if not range_pages or pages <= range_pages:
        return [None]
    return [(start, min(start + range_pages - 1, pages)) for start in range(1, pages + 1, range_pages)]


def convert_pdf(raw: bytes, name: str = "document.pdf", range_pages: int = 0) -> Conversion:
    """Parse the bytes of one PDF. Never raises; any status but SUCCESS is an error.

    A partial result (Docling's time limit stops a document between steps) counts as failed.
    With ``range_pages``, a longer PDF is parsed in ranges of that many pages and the parts
    are joined with ``DoclingDocument.concatenate``; the parts keep their page numbers
    (checked on an 8-page fixture with Docling 2.153.0). A failed range fails the document.
    """
    t0 = time.time()
    try:
        if raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
        from docling.datamodel.base_models import ConversionStatus, DocumentStream
        from docling_core.types.doc import DoclingDocument

        ranges = page_ranges(pdf_page_count(raw) if range_pages else 0, range_pages)
        parts = []
        for rng in ranges:
            extra = {"page_range": rng} if rng else {}
            res = build_converter().convert(DocumentStream(name=name, stream=BytesIO(raw)),
                                            raises_on_error=False, **extra)
            if res.status != ConversionStatus.SUCCESS:
                errors = "; ".join(str(e) for e in (res.errors or []))[:500]
                where = f" in pages {rng[0]}-{rng[1]}" if rng else ""
                return Conversion(status=res.status.name, error=f"status {res.status.name}{where}: {errors}",
                                  seconds=time.time() - t0)
            parts.append(res.document)
        doc = parts[0] if len(parts) == 1 else DoclingDocument.concatenate(parts)
    except Exception as exc:  # noqa: BLE001 — a parser never raises
        return Conversion(status="exception", error=f"{type(exc).__name__}: {exc}"[:500], seconds=time.time() - t0)
    seconds = time.time() - t0
    counts = {"pages": len(doc.pages), "tables": len(doc.tables),
              "cells": sum(len(t.data.table_cells) for t in doc.tables),
              "tables_without_cells": sum(1 for t in doc.tables if not t.data.table_cells),
              "page_ranges": len(ranges)}
    return Conversion(status="SUCCESS", document=doc.export_to_dict(), markdown=doc.export_to_markdown(),
                      pages=len(doc.pages), seconds=seconds, counts=counts)


VERSIONED_PACKAGES = ("docling", "docling-core", "docling-ibm-models", "docling-parse", "torch",
                      "transformers", "rapidocr", "onnxruntime", "pypdfium2")


def package_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for name in VERSIONED_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "missing"
    return out


def device() -> str:
    try:
        import torch

        return f"cuda:{torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


class DoclingPdfParser:
    """The ``docling`` parser on the :class:`corpus.parsers.base.Parser` protocol."""

    name: str = PARSER_NAME

    @property
    def version(self) -> str:
        return parser_version(docling_version(), OPTIONS_HASH)

    def parse(self, raw: bytes, url: str, content_type: str = "application/pdf") -> ParsedDocument:
        try:
            import docling  # noqa: F401
        except ImportError as exc:
            conv = Conversion(status="missing", error=f"missing_extra: docling is not installed here ({exc}); use the parse environment")
        else:
            conv = convert_pdf(raw if isinstance(raw, bytes) else b"", name=url.rsplit("/", 1)[-1] or "document.pdf")
        return ParsedDocument(
            url=url, parser=self.name, parser_version=self.version, parsed_at=datetime.now(UTC),
            content_type=content_type or "application/pdf", text=conv.markdown, text_format="markdown",
            error=conv.error, meta={"options_hash": OPTIONS_HASH, "seconds": round(conv.seconds, 2), **conv.counts},
        )
