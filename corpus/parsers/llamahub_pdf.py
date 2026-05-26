"""LlamaHub PDF demo parser (MIGR-014).

A second PDF parser that plugs into the same Parser protocol as
``pymupdf4llm`` so the parser-swap workflow can be exercised end-to-end.
Behind the ``[parsers-llamahub]`` optional extra: importing
``corpus.parsers`` does not pull in llama-index-readers-file by default;
only this module's ``parse`` path touches the dependency.

Reader: ``llama_index.readers.file.PDFReader`` (concrete choice — the
package re-exports its version via ``llama_index_readers_file``).

``raw`` semantics for ``parse``:
    bytes  — raw PDF bytes. Written to a temp file because PDFReader
             reads from disk.
    str    — filesystem path to a PDF.

Errors flow through ``ParsedDocument.error`` so the sync layer keeps
moving when a single PDF can't be parsed.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from corpus.parsers.base import ParsedDocument

_log = logging.getLogger(__name__)

_READER_PKG = "llama-index-readers-file"
_READER_CLASS = "PDFReader"
PARSER_NAME = f"llamahub_pdf_{_READER_CLASS}"


def _resolve_version() -> str:
    try:
        return version(_READER_PKG)
    except PackageNotFoundError:
        return "unknown"


PARSER_VERSION = _resolve_version()


def _import_reader():
    """Import PDFReader lazily so just importing this module doesn't require
    the optional extra. Raises ImportError with a clear message when the
    package isn't installed."""
    try:
        from llama_index.readers.file import PDFReader  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised when extra absent
        raise ImportError(
            "corpus.parsers.llamahub_pdf requires the [parsers-llamahub] "
            "extra: pip install 'ema-nlp[parsers-llamahub]' "
            "(installs llama-index-readers-file)."
        ) from exc
    return PDFReader


class LlamaHubPDFParser:
    """PDF parser backed by llama_index.readers.file.PDFReader.

    Conforms to :class:`corpus.parsers.base.Parser`.
    """

    name: str = PARSER_NAME
    version: str = PARSER_VERSION

    def __init__(self) -> None:
        # Lazy: defer the reader instantiation until parse() so import
        # of this module never fails when the extra is missing.
        self._reader = None

    def _get_reader(self):
        if self._reader is None:
            self._reader = _import_reader()()
        return self._reader

    def parse(
        self,
        raw: bytes | str,
        url: str,
        content_type: str = "application/pdf",
    ) -> ParsedDocument:
        parsed_at = datetime.now(UTC)
        if raw is None or (isinstance(raw, (bytes, str)) and not raw):
            return ParsedDocument(
                url=url,
                parser=self.name,
                parser_version=self.version,
                parsed_at=parsed_at,
                content_type=content_type or "application/pdf",
                text="",
                text_format="markdown",
                error="empty_input",
            )

        tmp_path: Path | None = None
        try:
            if isinstance(raw, bytes):
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(raw)
                    tmp_path = Path(f.name)
                pdf_path = tmp_path
            else:
                pdf_path = Path(raw)

            reader = self._get_reader()
            docs = reader.load_data(file=pdf_path)
            text = "\n\n".join(getattr(d, "text", "") or "" for d in docs).strip()
        except ImportError as exc:
            return ParsedDocument(
                url=url,
                parser=self.name,
                parser_version=self.version,
                parsed_at=parsed_at,
                content_type=content_type or "application/pdf",
                text="",
                text_format="markdown",
                error=f"missing_extra: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — diagnostics flow through .error
            return ParsedDocument(
                url=url,
                parser=self.name,
                parser_version=self.version,
                parsed_at=parsed_at,
                content_type=content_type or "application/pdf",
                text="",
                text_format="markdown",
                error=f"llamahub_parse_failed: {exc}",
            )
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        return ParsedDocument(
            url=url,
            parser=self.name,
            parser_version=self.version,
            parsed_at=parsed_at,
            content_type=content_type or "application/pdf",
            text=text,
            text_format="markdown",
            error="" if text else "empty_extraction",
        )
