"""URL- and text-derived metadata extractors.

The two submodules cleanly separate what's derivable from the URL alone
(``url_metadata``) from what requires the parsed body text
(``text_metadata``). Both are consumed by the ingest layer in
``harness.indexing.ingest`` (metadata derivation) and the link extractor.
"""

from corpus.metadata.text_metadata import (
    EMA_REF_RE,
    TextMetadata,
    text_metadata,
)
from corpus.metadata.url_metadata import UrlMetadata, url_metadata

__all__ = [
    "EMA_REF_RE",
    "TextMetadata",
    "UrlMetadata",
    "text_metadata",
    "url_metadata",
]
