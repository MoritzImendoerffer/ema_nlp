"""Tests for harness/query_cache.py (TASK-027.5)."""

from __future__ import annotations

import numpy as np
import pytest

from harness.query_cache import EMBED_DIM, QueryCache, _normalize


def _vec(seed: int) -> np.ndarray:
    """Return a deterministic unit vector of length EMBED_DIM."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBED_DIM).astype(np.float32)
    return _normalize(v.reshape(1, -1)).squeeze()


def _embed_fn(seed: int):
    """Return a callable that always returns the same vector (seed-based)."""
    v = _vec(seed)
    return lambda text: v


# ---------------------------------------------------------------------------
# Empty cache behaviour
# ---------------------------------------------------------------------------

def test_empty_cache_returns_nothing(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    results = cache.get_similar(_vec(0))
    assert results == []
    assert len(cache) == 0


# ---------------------------------------------------------------------------
# add_entry + get_similar
# ---------------------------------------------------------------------------

def test_add_and_retrieve_self(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    v = _vec(42)
    cache.add_entry("run-1", "What is AI?", "AI is Acceptable Intake.", ["qa001"], query_vec=v)
    results = cache.get_similar(v, k=1, threshold=0.99)
    assert len(results) == 1
    entry, sim = results[0]
    assert entry.run_id == "run-1"
    assert sim > 0.99


def test_dissimilar_query_filtered_out(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    cache.add_entry("run-1", "Q1", "A1", [], query_vec=_vec(1))
    cache.add_entry("run-2", "Q2", "A2", [], query_vec=_vec(2))
    # _vec(1) and _vec(99) are nearly orthogonal → similarity ≈ 0
    results = cache.get_similar(_vec(99), k=5, threshold=0.5)
    assert results == []


def test_returns_up_to_k(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    v = _vec(7)
    for i in range(5):
        cache.add_entry(f"run-{i}", f"Q{i}", f"A{i}", [], query_vec=v)
    results = cache.get_similar(v, k=3, threshold=0.99)
    assert len(results) == 3


# ---------------------------------------------------------------------------
# min_rating filter
# ---------------------------------------------------------------------------

def test_min_rating_filter(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    v = _vec(5)
    cache.add_entry("run-a", "Q", "A", [], query_vec=v)
    cache.add_entry("run-b", "Q", "A", [], query_vec=v)
    cache.update_rating("run-a", 5.0)
    cache.update_rating("run-b", 2.0)

    results = cache.get_similar(v, k=5, min_rating=4.0, threshold=0.5)
    run_ids = [e.run_id for e, _ in results]
    assert "run-a" in run_ids
    assert "run-b" not in run_ids


# ---------------------------------------------------------------------------
# update_rating
# ---------------------------------------------------------------------------

def test_update_rating_persists(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    cache.add_entry("run-x", "Q", "A", ["qa1"], query_vec=_vec(3))
    found = cache.update_rating("run-x", 4.5)
    assert found is True
    assert cache._entries[0].rating == pytest.approx(4.5)


def test_update_rating_missing_run_id(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    found = cache.update_rating("nonexistent", 3.0)
    assert found is False


# ---------------------------------------------------------------------------
# Persistence (reload from disk)
# ---------------------------------------------------------------------------

def test_reload_from_disk(tmp_path):
    v = _vec(10)
    cache1 = QueryCache(index_dir=tmp_path)
    cache1.add_entry("run-persist", "Q persist", "A persist", ["qa99"], query_vec=v)
    cache1.update_rating("run-persist", 5.0)

    # Fresh instance loads from same directory
    cache2 = QueryCache(index_dir=tmp_path)
    assert len(cache2) == 1
    entry = cache2._entries[0]
    assert entry.run_id == "run-persist"
    assert entry.rating == pytest.approx(5.0)
    assert entry.cited_qa_ids == ["qa99"]

    results = cache2.get_similar(v, k=1, threshold=0.99)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# embed_fn path
# ---------------------------------------------------------------------------

def test_add_entry_with_embed_fn(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    v = _vec(20)
    embed = lambda text: v  # noqa: E731
    cache.add_entry("run-fn", "Question via fn", "Answer", [], embed_fn=embed)
    results = cache.get_similar(v, k=1, threshold=0.99)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# cited_qa_ids stored and retrieved
# ---------------------------------------------------------------------------

def test_cited_qa_ids_stored(tmp_path):
    cache = QueryCache(index_dir=tmp_path)
    v = _vec(30)
    cache.add_entry("run-cit", "Q", "A", ["qa-001", "qa-002"], query_vec=v)
    results = cache.get_similar(v, k=1, threshold=0.99)
    assert results[0][0].cited_qa_ids == ["qa-001", "qa-002"]


# ---------------------------------------------------------------------------
# F4: shared instance + concurrent writes
# ---------------------------------------------------------------------------

def test_get_query_cache_returns_shared_instance(tmp_path):
    from harness.query_cache import get_query_cache

    a = get_query_cache(tmp_path)
    b = get_query_cache(tmp_path)
    assert a is b  # separate instances would clobber each other's saves (F4)


def test_concurrent_adds_and_ratings_all_persist(tmp_path):
    """Entries + ratings written from many threads all survive a reload (F4)."""
    import threading

    cache = QueryCache(index_dir=tmp_path)
    n = 16

    def _write(i: int) -> None:
        cache.add_entry(f"run-{i}", f"Q{i}", f"A{i}", [], query_vec=_vec(i))
        cache.update_rating(f"run-{i}", 5.0)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    reloaded = QueryCache(index_dir=tmp_path)
    assert len(reloaded) == n
    ratings = {e.run_id: e.rating for e in reloaded._entries}
    assert all(ratings[f"run-{i}"] == 5.0 for i in range(n))
    # No stray tmp files left behind by the atomic writes.
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------------
# F12: embedding-model provenance
# ---------------------------------------------------------------------------

def test_sidecar_records_embed_model_and_legacy_list_still_loads(tmp_path):
    import json

    cache = QueryCache(index_dir=tmp_path, embed_model="BAAI/bge-large-en-v1.5")
    cache.add_entry("run-p", "Q", "A", [], query_vec=_vec(1))
    sidecar = json.loads((tmp_path / "query_cache.json").read_text())
    assert sidecar["embed_model"] == "BAAI/bge-large-en-v1.5"
    assert len(sidecar["entries"]) == 1

    # Legacy bare-list sidecar is still accepted (provenance adopted on next save).
    (tmp_path / "query_cache.json").write_text(json.dumps(sidecar["entries"]))
    legacy = QueryCache(index_dir=tmp_path, embed_model="BAAI/bge-large-en-v1.5")
    assert len(legacy) == 1


def test_embed_model_mismatch_backs_up_and_starts_fresh(tmp_path):
    cache = QueryCache(index_dir=tmp_path, embed_model="model-A")
    cache.add_entry("run-a", "Q", "A", [], query_vec=_vec(2))

    switched = QueryCache(index_dir=tmp_path, embed_model="model-B")
    assert len(switched) == 0  # never mixes embedding spaces (F12)
    backups = sorted(p.name for p in tmp_path.glob("*.bak-*"))
    assert backups == ["query_cache.faiss.bak-model-A", "query_cache.json.bak-model-A"]

    # The fresh cache persists under the new model without touching the backup.
    switched.add_entry("run-b", "Q2", "A2", [], query_vec=_vec(3))
    reloaded = QueryCache(index_dir=tmp_path, embed_model="model-B")
    assert [e.run_id for e in reloaded._entries] == ["run-b"]
