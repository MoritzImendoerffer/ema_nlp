"""BGE embedder + pgvector ingest pipeline.

This module hosts two layers:

* `Embedder` — thin wrapper around the LlamaIndex BGE-large-en-v1.5 embedding
  model with CUDA autodetection. Used by both the FAISS (legacy) and pgvector
  (new) paths; here we configure LlamaIndex Settings via
  `harness.providers.configure_embed_model` and call
  `Settings.embed_model.get_text_embedding_batch`.

* `ingest_source` (NARR-007 + NARR-010) — CLI-driven loop that streams
  MongoDB docs, normalises, chunks, embeds in batches, and bulk-upserts into
  the `documents` + `chunks` (+ `links`) tables. Lives in the same module so
  the Embedder construction stays adjacent to its only caller.

Constants:
    EMBED_MODEL_NAME, EMBED_DIM   imported from harness.embed so the two
                                  retrieval backends never drift on model.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from llama_index.core.settings import Settings

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness.embed import EMBED_DIM, EMBED_MODEL_NAME  # noqa: E402 — re-export
from harness.providers import configure_embed_model  # noqa: E402

_log = logging.getLogger(__name__)


def _detect_device() -> str:
    try:
        import torch  # heavy import; only used to pick device
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


class Embedder:
    """LlamaIndex-backed BGE embedder. Lazy: model loads on first use."""

    def __init__(
        self,
        *,
        device: str | None = None,
        batch_size: int = 32,
        model_name: str | None = None,
    ) -> None:
        self.device = device or _detect_device()
        self.batch_size = batch_size
        self.model_name = model_name or EMBED_MODEL_NAME
        self._configured = False

    def _ensure(self) -> None:
        if self._configured:
            return
        configure_embed_model(
            model_name=self.model_name, device=self.device, embed_batch_size=self.batch_size
        )
        _log.info(
            "Embedder ready: model=%s device=%s batch_size=%d dim=%d",
            self.model_name, self.device, self.batch_size, EMBED_DIM,
        )
        self._configured = True

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of EMBED_DIM-length float lists."""
        if not texts:
            return []
        self._ensure()
        vectors = Settings.embed_model.get_text_embedding_batch(list(texts))
        return [list(map(float, v)) for v in vectors]


def _smoke_test() -> int:
    """Verify Embedder builds, runs, and returns (8, 1024) shapes."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    embedder = Embedder()
    texts = [
        "Acceptable intake (AI) is a toxicology limit in ng/day.",
        "EMA/CHMP/13279/2017 references a specific committee work plan.",
        "Reference Listed Drugs are used in bioequivalence studies.",
        "ICH M7 sets the mutagenic-impurity control framework.",
        "Class 1 solvents are residual solvents to avoid.",
        "Q3D guideline addresses metallic-impurity exposure.",
        "Variation type II requires new data submission.",
        "PRAC reviews pharmacovigilance signals quarterly.",
    ]
    assert len(texts) == 8
    vectors = embedder.encode(texts)
    assert len(vectors) == 8, f"expected 8 vectors, got {len(vectors)}"
    assert all(len(v) == EMBED_DIM for v in vectors), "wrong dimension"
    assert all(isinstance(x, float) for v in vectors for x in v[:4]), "non-float entries"
    print(
        f"embed_pg.Embedder smoke OK: 8x{EMBED_DIM} vectors, device={embedder.device}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_smoke_test())
