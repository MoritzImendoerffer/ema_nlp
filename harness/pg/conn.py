"""Lazy psycopg_pool + pgvector type registration.

`get_pool()` returns a process-singleton `psycopg_pool.ConnectionPool` pointed
at `config.PG_DSN`. Every new connection in the pool has the pgvector type
registered via `pgvector.psycopg.register_vector` so `vector(1024)` columns
round-trip as numpy arrays / Python lists transparently.

The pool is opened lazily on first call and closed via `close_pool()` (used
by tests and the `__main__` smoke test below).
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from config import PG_DSN  # noqa: E402

_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()


def _configure(conn) -> None:
    """psycopg_pool `configure` hook — runs once per new connection."""
    register_vector(conn)


def get_pool(
    dsn: str | None = None,
    *,
    min_size: int = 1,
    max_size: int = 8,
    timeout: float = 30.0,
) -> ConnectionPool:
    """Return the singleton pool. First caller wins for sizing.

    Args:
        dsn: override PG_DSN (e.g. PG_DSN_TEST). If a pool already exists,
            this argument is ignored (pool is process-singleton).
        min_size, max_size: pool sizing on first construction.
        timeout: max seconds to wait for a connection from the pool.
    """
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            chosen = dsn or os.getenv("PG_DSN", PG_DSN)
            _pool = ConnectionPool(
                conninfo=chosen,
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
                configure=_configure,
                open=True,
            )
    return _pool


def close_pool() -> None:
    """Close the singleton pool. Safe to call when no pool exists."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def _smoke_test() -> int:
    """Verify pool, SELECT 1, and 1024-dim vector round-trip."""
    import numpy as np

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            (one,) = cur.fetchone()
            assert one == 1, f"SELECT 1 returned {one!r}"

            vec = np.arange(1024, dtype=np.float32) / 1024.0
            cur.execute("SELECT %s::vector(1024) AS v", (vec.tolist(),))
            (roundtrip,) = cur.fetchone()
            arr = np.asarray(roundtrip, dtype=np.float32)
            assert arr.shape == (1024,), f"shape {arr.shape}"
            np.testing.assert_allclose(arr, vec, atol=1e-6)
    close_pool()
    print("conn.py smoke: pool OK, SELECT 1 OK, vector(1024) round-trip OK")
    return 0


if __name__ == "__main__":
    sys.exit(_smoke_test())
