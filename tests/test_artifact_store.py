"""Tests for scripts/lib/_artifact_store.sh — DBSYNC-001."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lib" / "_artifact_store.sh"


def _run(snippet: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Source the helper and run a bash snippet against it."""
    bash_code = f"set -eu; source {SCRIPT}; {snippet}"
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", bash_code],
        env=full_env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def isolated_store(tmp_path: Path) -> dict[str, str]:
    """Env vars pointing the nextcloud backend at an isolated tmp dir."""
    return {
        "STORAGE_BACKEND": "nextcloud",
        "NEXTCLOUD_DATASETS": str(tmp_path),
        "ARTIFACT_DIR_NAME": "db_sync",
        # Prevent the test process's $HOME from leaking in via defaults.
        "HOME": str(tmp_path / "home"),
    }


class TestArtifactStore:
    def test_put_and_get_round_trip(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"hello world")
        dst = tmp_path / "dst.bin"

        result = _run(f'_put_artifact "{src}" "test.bin"', env=isolated_store)
        assert result.returncode == 0, result.stderr

        artifact = tmp_path / "db_sync" / "test.bin"
        assert artifact.exists()
        assert artifact.read_bytes() == b"hello world"

        result = _run(f'_get_artifact "test.bin" "{dst}"', env=isolated_store)
        assert result.returncode == 0, result.stderr
        assert dst.read_bytes() == b"hello world"

    def test_put_leaves_no_partial_on_success(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"x" * 1024)
        _run(f'_put_artifact "{src}" "atomic.bin"', env=isolated_store)
        names = sorted(f.name for f in (tmp_path / "db_sync").iterdir())
        assert names == ["atomic.bin"], names

    def test_put_errors_on_missing_local_file(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        result = _run(
            f'_put_artifact "{tmp_path / "nope.bin"}" "x.bin"', env=isolated_store
        )
        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_put_requires_artifact_name(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"x")
        result = _run(f'_put_artifact "{src}" ""', env=isolated_store)
        assert result.returncode != 0
        assert "artifact_name required" in result.stderr

    def test_get_errors_on_missing(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        result = _run(
            f'_get_artifact "absent.bin" "{tmp_path / "out.bin"}"', env=isolated_store
        )
        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_stat_artifact_format(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"x" * 42)
        _run(f'_put_artifact "{src}" "stat_me.bin"', env=isolated_store)

        result = _run('_stat_artifact "stat_me.bin"', env=isolated_store)
        assert result.returncode == 0, result.stderr
        parts = result.stdout.strip().split()
        assert len(parts) == 2, f"expected '<bytes> <mtime>', got {result.stdout!r}"
        bytes_field, mtime_field = parts
        assert int(bytes_field) == 42
        assert int(mtime_field) > 0

    def test_stat_missing_returns_nonzero(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        result = _run('_stat_artifact "absent.bin"', env=isolated_store)
        assert result.returncode != 0

    def test_artifact_exists(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"x")
        _run(f'_put_artifact "{src}" "present.bin"', env=isolated_store)

        assert _run('_artifact_exists "present.bin"', env=isolated_store).returncode == 0
        assert _run('_artifact_exists "absent.bin"', env=isolated_store).returncode != 0

    def test_list_artifacts(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        src = tmp_path / "src"
        src.write_bytes(b"x")
        for name in ["a.bin", "b.bin", "c.bin"]:
            _run(f'_put_artifact "{src}" "{name}"', env=isolated_store)

        result = _run("_list_artifacts", env=isolated_store)
        assert result.returncode == 0, result.stderr
        assert sorted(result.stdout.strip().splitlines()) == ["a.bin", "b.bin", "c.bin"]

    def test_list_excludes_partial_files(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        base = tmp_path / "db_sync"
        base.mkdir(parents=True)
        (base / "real.bin").write_bytes(b"x")
        (base / "ghost.bin.partial").write_bytes(b"x")

        result = _run("_list_artifacts", env=isolated_store)
        assert result.stdout.strip() == "real.bin"

    def test_list_empty_dir(self, isolated_store: dict[str, str]) -> None:
        result = _run("_list_artifacts", env=isolated_store)
        assert result.returncode == 0
        assert result.stdout == ""

    def test_unknown_backend_errors(self, tmp_path: Path) -> None:
        env = {
            "STORAGE_BACKEND": "moonshot",
            "NEXTCLOUD_DATASETS": str(tmp_path),
            "HOME": str(tmp_path / "home"),
        }
        result = _run('_artifact_exists "anything"', env=env)
        assert result.returncode != 0
        assert "moonshot" in result.stderr
        assert "supported: nextcloud" in result.stderr

    def test_sourcing_is_side_effect_free(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        """Sourcing alone must NOT create the artifact directory."""
        result = _run(":", env=isolated_store)
        assert result.returncode == 0
        assert not (tmp_path / "db_sync").exists()

    def test_double_source_is_idempotent(
        self, tmp_path: Path, isolated_store: dict[str, str]
    ) -> None:
        """Second source must be a no-op (guard variable)."""
        snippet = (
            f"source {SCRIPT}; "
            f"source {SCRIPT}; "
            f"src={tmp_path}/dbl; echo x > $src; "
            f'_put_artifact "$src" "twice.bin"'
        )
        result = subprocess.run(
            ["bash", "-c", f"set -eu; {snippet}"],
            env={**os.environ, **isolated_store},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "db_sync" / "twice.bin").exists()
