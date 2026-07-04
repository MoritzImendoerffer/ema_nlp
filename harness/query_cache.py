"""
Semantic query cache: a secondary FAISS index over past query embeddings.

Stores past Q&A interactions so similar future queries can reuse or be primed
by them (see TASK-027.6/027.7). Uses the same BGE-large-en embedding space as
the main corpus index, so cosine distances are directly comparable.

Persistence layout (paths relative to INDEX_DIR from config.py):
    query_cache.faiss  — FAISS flat-IP index (inner product ≈ cosine on unit vecs)
    query_cache.json   — sidecar: list of entry dicts, position == FAISS vector id

Usage:
    cache = get_query_cache()     # process-wide shared instance (loads or starts empty)
    cache.add_entry(...)          # append an interaction
    cache.get_similar(vec, k=3)   # find similar past queries
    cache.update_rating(run_id, 5)

Concurrency: one shared ``QueryCache`` per index dir (``get_query_cache``), with a
lock around mutations and atomic tmp+rename writes — concurrent Chainlit sessions
in one process no longer clobber each other's entries/ratings (F4). Multiple
*processes* sharing the files are still last-writer-wins (out of scope: the app
runs as a single process).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from config import INDEX_DIR

log = logging.getLogger(__name__)

EMBED_DIM = 1024  # BGE-large-en-v1.5 output dimension
DEFAULT_THRESHOLD = 0.88
_FAISS_FILE = "query_cache.faiss"
_JSON_FILE = "query_cache.json"


@dataclass
class CacheEntry:
    run_id: str
    question_text: str
    answer_summary: str
    rating: float | None
    cited_qa_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CacheEntry:
        return cls(**d)


class QueryCache:
    """FAISS-backed semantic cache for past query–answer interactions."""

    def __init__(self, index_dir: Path = INDEX_DIR) -> None:
        self._faiss_path = index_dir / _FAISS_FILE
        self._json_path = index_dir / _JSON_FILE
        self._index_dir = index_dir
        self._entries: list[CacheEntry] = []
        self._faiss_index: faiss.IndexFlatIP = faiss.IndexFlatIP(EMBED_DIM)
        # Guards _entries + _faiss_index across sessions/threads (app writes happen
        # on worker threads via make_async). Reentrant so locked methods may nest.
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._faiss_path.exists() and self._json_path.exists():
            self._faiss_index = faiss.read_index(str(self._faiss_path))
            raw = json.loads(self._json_path.read_text(encoding="utf-8"))
            self._entries = [CacheEntry.from_dict(e) for e in raw]
            log.info("Query cache loaded: %d entries", len(self._entries))
        else:
            log.info("Query cache empty — starting fresh")

    def _save(self) -> None:
        """Persist atomically (tmp + rename) so a crash mid-write never truncates."""
        self._index_dir.mkdir(parents=True, exist_ok=True)
        faiss_tmp = self._faiss_path.with_suffix(".faiss.tmp")
        json_tmp = self._json_path.with_suffix(".json.tmp")
        faiss.write_index(self._faiss_index, str(faiss_tmp))
        json_tmp.write_text(
            json.dumps([e.to_dict() for e in self._entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(faiss_tmp, self._faiss_path)
        os.replace(json_tmp, self._json_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_entry(
        self,
        run_id: str,
        question: str,
        answer: str,
        cited_qa_ids: list[str],
        query_vec: np.ndarray | None = None,
        *,
        embed_fn: Any = None,
    ) -> None:
        """
        Append one interaction to the cache.

        Either pass a pre-computed ``query_vec`` (shape (1024,)) or an
        ``embed_fn(text) -> np.ndarray`` callable to compute it on the fly.
        If neither is provided the entry is stored without a vector (it will
        not be retrievable by similarity search).
        """
        entry = CacheEntry(
            run_id=run_id,
            question_text=question,
            answer_summary=answer,
            rating=None,
            cited_qa_ids=cited_qa_ids,
        )
        if query_vec is None and embed_fn is not None:
            query_vec = embed_fn(question)

        with self._lock:
            self._entries.append(entry)
            if query_vec is not None:
                vec = _normalize(np.asarray(query_vec, dtype=np.float32).reshape(1, -1))
                self._faiss_index.add(vec)
            else:
                # Pad index with a zero vector so sidecar indices stay aligned
                self._faiss_index.add(np.zeros((1, EMBED_DIM), dtype=np.float32))
            self._save()
        log.debug("Cache: added entry run_id=%s", run_id)

    def get_similar(
        self,
        query_vec: np.ndarray,
        k: int = 5,
        min_rating: float | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> list[tuple[CacheEntry, float]]:
        """
        Return up to k cache entries whose cosine similarity exceeds threshold.

        Args:
            query_vec:  Query embedding vector (shape (1024,)).
            k:          Maximum number of results.
            min_rating: If set, only return entries with rating >= min_rating.
            threshold:  Minimum cosine similarity (0–1).

        Returns:
            List of (entry, similarity) sorted descending by similarity.
        """
        with self._lock:
            if self._faiss_index.ntotal == 0:
                return []

            vec = _normalize(np.asarray(query_vec, dtype=np.float32).reshape(1, -1))
            k_search = min(k * 3, self._faiss_index.ntotal)  # over-fetch for rating filter
            scores, indices = self._faiss_index.search(vec, k_search)

            results: list[tuple[CacheEntry, float]] = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self._entries):
                    continue
                sim = float(score)
                if sim < threshold:
                    continue
                entry = self._entries[idx]
                if min_rating is not None and (entry.rating is None or entry.rating < min_rating):
                    continue
                results.append((entry, sim))
                if len(results) >= k:
                    break

        return results

    def update_rating(self, run_id: str, rating: float) -> bool:
        """
        Set rating on the entry matching run_id. Returns True if found.
        """
        with self._lock:
            for entry in self._entries:
                if entry.run_id == run_id:
                    entry.rating = rating
                    self._save()
                    log.debug("Cache: rated run_id=%s → %.1f", run_id, rating)
                    return True
        log.warning("Cache: run_id %s not found for rating", run_id)
        return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_INSTANCES: dict[Path, QueryCache] = {}
_INSTANCES_LOCK = threading.Lock()


def get_query_cache(index_dir: Path = INDEX_DIR) -> QueryCache:
    """Process-wide shared ``QueryCache`` for ``index_dir``.

    All sessions must share one instance per cache-file pair — separate instances
    each hold their own in-memory snapshot and their full-file rewrites clobber
    each other's entries and ratings (F4).
    """
    key = Path(index_dir).resolve()
    with _INSTANCES_LOCK:
        cache = _INSTANCES.get(key)
        if cache is None:
            cache = _INSTANCES[key] = QueryCache(index_dir)
        return cache


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize rows so inner product == cosine similarity."""
    norms = np.linalg.norm(vec, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vec / norms
