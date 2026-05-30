"""Tests for the DBSYNC-004 extensions to scripts/sync_mongo.sh.

Round-trip integration is deferred to DBSYNC-010; here we cover argv parsing,
the --yes flag, manifest behaviour, sha256 mismatch rejection, and the legacy
archive deprecation warning.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sync_mongo.sh"


def _run(
    args: list[str],
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=full_env,
        capture_output=True,
        text=True,
        input=stdin,
    )


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    return {
        "STORAGE_BACKEND": "nextcloud",
        "NEXTCLOUD_DATASETS": str(tmp_path),
        "HOME": str(tmp_path / "home"),
        # Point at a mongo URI that definitely won't connect (won't be used in
        # the cli/error-path tests below).
        "MONGO_URI": "mongodb://localhost:9999/",
    }


class TestSyncMongoCli:
    def test_help_works(self, isolated_env: dict[str, str]) -> None:
        result = _run(["--help"], env=isolated_env)
        assert result.returncode == 0
        assert "Subcommands" in result.stdout
        assert "export" in result.stdout
        assert "import" in result.stdout
        assert "pull" in result.stdout

    def test_no_args_prints_help(self, isolated_env: dict[str, str]) -> None:
        result = _run([], env=isolated_env)
        assert result.returncode == 0
        assert "Usage" in result.stdout

    def test_unknown_subcommand_errors(self, isolated_env: dict[str, str]) -> None:
        result = _run(["bogus"], env=isolated_env)
        assert result.returncode != 0
        assert "Unknown subcommand" in result.stderr

    def test_unknown_flag_errors(self, isolated_env: dict[str, str]) -> None:
        result = _run(["export", "--never-heard-of"], env=isolated_env)
        assert result.returncode != 0
        assert "Unknown flag" in result.stderr


class TestSyncMongoImportArchiveChecks:
    def test_import_errors_when_archive_missing(
        self, isolated_env: dict[str, str]
    ) -> None:
        result = _run(["import", "--yes"], env=isolated_env)
        assert result.returncode != 0
        assert "not found in artifact store" in result.stderr

    def test_import_rejects_sha256_mismatch(
        self, tmp_path: Path, isolated_env: dict[str, str]
    ) -> None:
        # Plant an archive and a manifest claiming a different sha256.
        artifact_dir = tmp_path / "db_sync"
        artifact_dir.mkdir()
        archive = artifact_dir / "mongo.archive.gz"
        archive.write_bytes(b"\x1f\x8b\x08fakegzipdata")

        manifest = artifact_dir / "mongo.archive.gz.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "exported_at": "2026-05-30T00:00:00+00:00",
                    "source_host": "test",
                    "git_commit": "test",
                    "mongo": {
                        "archive": "mongo.archive.gz",
                        "bytes": len(archive.read_bytes()),
                        "sha256": "deadbeef_wrong_hash_does_not_match_anything_at_all",
                        "db_name": "ema_scraper",
                        "key_counts": {"web_items": 0},
                    },
                }
            )
        )

        result = _run(["import", "--yes"], env=isolated_env)
        assert result.returncode != 0
        assert "MISMATCH" in result.stderr or "mismatch" in result.stderr.lower()

    def test_import_skip_checksum_bypasses_verification(
        self, tmp_path: Path, isolated_env: dict[str, str]
    ) -> None:
        """With --skip-checksum, the sha256 check is bypassed.

        The script should then try mongorestore against the (invalid) archive
        and fail there — but NOT at the manifest verification step.
        """
        artifact_dir = tmp_path / "db_sync"
        artifact_dir.mkdir()
        archive = artifact_dir / "mongo.archive.gz"
        archive.write_bytes(b"\x1f\x8b\x08fakegzipdata")

        manifest = artifact_dir / "mongo.archive.gz.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "exported_at": "2026-05-30T00:00:00+00:00",
                    "source_host": "test",
                    "git_commit": "test",
                    "mongo": {
                        "archive": "mongo.archive.gz",
                        "bytes": len(archive.read_bytes()),
                        "sha256": "deadbeef_wrong",
                        "db_name": "ema_scraper",
                        "key_counts": {"web_items": 0},
                    },
                }
            )
        )

        result = _run(
            ["import", "--yes", "--skip-checksum"],
            env=isolated_env,
        )
        # Should still fail (no live mongo on port 9999, or mongorestore reports
        # bad archive) — but the error should NOT be a sha256 mismatch.
        assert result.returncode != 0
        assert "MISMATCH" not in result.stderr
        assert "mismatch" not in result.stderr.lower()


class TestSyncMongoLegacyDeprecation:
    def test_legacy_archive_triggers_deprecation_warning(
        self, tmp_path: Path, isolated_env: dict[str, str]
    ) -> None:
        # Plant the legacy archive AND a valid-ish new archive so import gets
        # past the missing-archive check (it'll then fail at mongorestore, but
        # the deprecation warning must appear regardless).
        legacy_dir = tmp_path / "mongo_sync"
        legacy_dir.mkdir()
        (legacy_dir / "ema_scraper.archive").write_bytes(b"legacy")

        new_dir = tmp_path / "db_sync"
        new_dir.mkdir()
        (new_dir / "mongo.archive.gz").write_bytes(b"\x1f\x8b\x08fake")

        result = _run(["import", "--yes", "--skip-checksum"], env=isolated_env)
        # Warning is written to stderr.
        assert "Legacy archive detected" in result.stderr


class TestSyncMongoYesFlag:
    def test_yes_flag_is_accepted(self, isolated_env: dict[str, str]) -> None:
        """--yes parses cleanly; the script then errors at a downstream check."""
        result = _run(["import", "--yes"], env=isolated_env)
        assert result.returncode != 0
        # We expect the artifact-missing error, NOT a flag-parsing error.
        assert "Unknown flag" not in result.stderr


class TestSyncMongoPullArgs:
    def test_pull_errors_without_host(self, isolated_env: dict[str, str]) -> None:
        env = {**isolated_env}
        env.pop("MONGO_SYNC_HOST", None)
        result = _run(["pull"], env=env)
        assert result.returncode != 0
        assert "Remote host required" in result.stderr

    def test_pull_accepts_yes_and_host(self, isolated_env: dict[str, str]) -> None:
        """Flag parsing: --yes + --host should not error at argv stage.

        SSH will fail (no reachable host) but that's beyond the parser.
        """
        result = _run(
            ["pull", "--yes", "--host", "definitely.not.a.real.host.invalid"],
            env=isolated_env,
        )
        assert result.returncode != 0
        # Not a flag-parsing error.
        assert "Unknown pull flag" not in result.stderr
        assert "Unknown flag" not in result.stderr
