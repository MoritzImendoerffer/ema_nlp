"""Tests for scripts/lib/_manifest.sh — DBSYNC-002."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_SH = ROOT / "scripts" / "lib" / "_manifest.sh"


def _run(snippet: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    bash_code = f"set -eu; source {MANIFEST_SH}; {snippet}"
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", bash_code],
        env=full_env,
        capture_output=True,
        text=True,
    )


class TestManifestInit:
    def test_init_writes_partial_with_skeleton(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        result = _run(f'_manifest_init "{out}"')
        assert result.returncode == 0, result.stderr

        partial = tmp_path / "manifest.json.partial"
        assert partial.exists()
        assert not out.exists()  # not finalised yet

        data = json.loads(partial.read_text())
        assert data["schema_version"] == 1
        assert data["source_host"]
        assert data["exported_at"]
        assert data["exported_at"].endswith("+00:00")
        assert "git_commit" in data

    def test_init_creates_parent_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "nested" / "manifest.json"
        result = _run(f'_manifest_init "{out}"')
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "sub" / "nested" / "manifest.json.partial").exists()

    def test_init_requires_out_file(self) -> None:
        result = _run('_manifest_init ""')
        assert result.returncode != 0
        assert "out_file required" in result.stderr


class TestManifestAddDb:
    def test_add_mongo_block(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        _run(f'_manifest_init "{out}"')

        counts = '{"web_items": 115101, "parsed_documents": 80083}'
        result = _run(
            f"_manifest_add_db \"{out}\" mongo mongo.archive.gz 1000 deadbeef "
            f"ema_scraper '{counts}'"
        )
        assert result.returncode == 0, result.stderr

        data = json.loads((tmp_path / "manifest.json.partial").read_text())
        assert data["mongo"] == {
            "archive": "mongo.archive.gz",
            "bytes": 1000,
            "sha256": "deadbeef",
            "db_name": "ema_scraper",
            "key_counts": {"web_items": 115101, "parsed_documents": 80083},
        }

    def test_add_both_dbs(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        _run(f'_manifest_init "{out}"')
        _run(
            f"_manifest_add_db \"{out}\" mongo m.gz 1 a ema_scraper '{{\"web_items\":1}}'"
        )
        _run(
            f"_manifest_add_db \"{out}\" postgres p.dump 2 b ema_nlp '{{\"chunks\":2}}'"
        )
        data = json.loads((tmp_path / "manifest.json.partial").read_text())
        assert data["mongo"]["bytes"] == 1
        assert data["postgres"]["bytes"] == 2

    def test_add_rejects_unknown_db_key(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        _run(f'_manifest_init "{out}"')
        result = _run(
            f"_manifest_add_db \"{out}\" cassandra a.gz 1 a x '{{\"k\":1}}'"
        )
        assert result.returncode != 0
        assert "mongo or postgres" in result.stderr

    def test_add_rejects_invalid_counts_json(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        _run(f'_manifest_init "{out}"')
        result = _run(
            f"_manifest_add_db \"{out}\" mongo a.gz 1 a x 'not json'"
        )
        assert result.returncode != 0
        assert "not valid JSON" in result.stderr

    def test_add_errors_without_init(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        result = _run(
            f"_manifest_add_db \"{out}\" mongo a.gz 1 a x '{{\"k\":1}}'"
        )
        assert result.returncode != 0
        assert "init not called" in result.stderr


class TestManifestFinalize:
    def test_finalize_renames_partial(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        _run(f'_manifest_init "{out}"')
        result = _run(f'_manifest_finalize "{out}"')
        assert result.returncode == 0, result.stderr
        assert out.exists()
        assert not (tmp_path / "manifest.json.partial").exists()

    def test_finalize_rejects_invalid_json(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        (tmp_path / "manifest.json.partial").write_text("{this is not json")
        result = _run(f'_manifest_finalize "{out}"')
        assert result.returncode != 0
        assert "not valid JSON" in result.stderr
        assert not out.exists()

    def test_finalize_errors_when_partial_missing(self, tmp_path: Path) -> None:
        result = _run(f'_manifest_finalize "{tmp_path / "manifest.json"}"')
        assert result.returncode != 0
        assert "nothing to finalize" in result.stderr


class TestManifestReadGet:
    def test_read_validates_json(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        out.write_text("{broken")
        result = _run(f'_manifest_read "{out}"')
        assert result.returncode != 0
        assert "not valid JSON" in result.stderr

    def test_read_returns_parsed(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        out.write_text(json.dumps({"schema_version": 1, "x": "y"}))
        result = _run(f'_manifest_read "{out}"')
        assert result.returncode == 0
        assert json.loads(result.stdout) == {"schema_version": 1, "x": "y"}

    def test_get_extracts_nested_field(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        out.write_text(json.dumps({"postgres": {"sha256": "abc123"}}))
        result = _run(f'_manifest_get "{out}" ".postgres.sha256"')
        assert result.returncode == 0
        assert result.stdout.strip() == "abc123"


class TestManifestVerifyArchive:
    def test_verify_matches(self, tmp_path: Path) -> None:
        archive = tmp_path / "pg.dump"
        archive.write_bytes(b"\x00" * 1024)
        expected_sha = hashlib.sha256(archive.read_bytes()).hexdigest()

        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"postgres": {"sha256": expected_sha}}))

        result = _run(
            f'_manifest_verify_archive "{manifest}" postgres "{archive}"'
        )
        assert result.returncode == 0, result.stderr

    def test_verify_rejects_mismatch(self, tmp_path: Path) -> None:
        archive = tmp_path / "pg.dump"
        archive.write_bytes(b"hello")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"postgres": {"sha256": "wronghash"}}))

        result = _run(
            f'_manifest_verify_archive "{manifest}" postgres "{archive}"'
        )
        assert result.returncode != 0
        assert "MISMATCH" in result.stderr

    def test_verify_errors_when_db_block_absent(self, tmp_path: Path) -> None:
        archive = tmp_path / "pg.dump"
        archive.write_bytes(b"x")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": 1}))

        result = _run(
            f'_manifest_verify_archive "{manifest}" postgres "{archive}"'
        )
        assert result.returncode != 0
        assert "no sha256 for postgres" in result.stderr


class TestManifestSet:
    def test_set_field_on_partial(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        _run(f'_manifest_init "{out}"')
        _run(
            f"_manifest_add_db \"{out}\" postgres pg.dump 1 a ema_nlp '{{\"chunks\":1}}'"
        )
        result = _run(f'_manifest_set "{out}" ".postgres.embeddings_excluded" "true"')
        assert result.returncode == 0, result.stderr
        data = json.loads((tmp_path / "manifest.json.partial").read_text())
        assert data["postgres"]["embeddings_excluded"] is True

    def test_set_field_on_finalised(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"
        _run(f'_manifest_init "{out}"')
        _run(f'_manifest_finalize "{out}"')
        result = _run(f'_manifest_set "{out}" ".extra" "\\"hello\\""')
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text())
        assert data["extra"] == "hello"

    def test_set_errors_when_target_missing(self, tmp_path: Path) -> None:
        result = _run(
            f'_manifest_set "{tmp_path / "nope.json"}" ".x" "1"'
        )
        assert result.returncode != 0


class TestManifestRoundTrip:
    def test_full_round_trip_with_real_sha(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.json"

        archive = tmp_path / "mongo.archive.gz"
        archive.write_bytes(b"fake archive bytes" * 100)
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        size = archive.stat().st_size

        snippet = (
            f'_manifest_init "{out}" && '
            f"_manifest_add_db \"{out}\" mongo mongo.archive.gz {size} {sha} ema_scraper '{{\"web_items\":42}}' && "
            f"_manifest_add_db \"{out}\" postgres pg.dump 999 abc ema_nlp '{{\"chunks\":10}}' && "
            f'_manifest_finalize "{out}"'
        )
        result = _run(snippet)
        assert result.returncode == 0, result.stderr

        data = json.loads(out.read_text())
        assert data["schema_version"] == 1
        assert data["mongo"]["sha256"] == sha
        assert data["mongo"]["key_counts"]["web_items"] == 42
        assert data["postgres"]["key_counts"]["chunks"] == 10

        verify = _run(f'_manifest_verify_archive "{out}" mongo "{archive}"')
        assert verify.returncode == 0, verify.stderr


@pytest.mark.skipif(
    subprocess.run(["which", "jq"], capture_output=True).returncode == 0,
    reason="jq is installed; cannot test the missing-jq error path",
)
class TestMissingJq:
    """Document the missing-jq error path; runs only if jq is unavailable."""

    def test_init_errors_when_jq_missing(self, tmp_path: Path) -> None:
        # We can't actually uninstall jq for the test, so this is a placeholder
        # that activates only on machines without jq. Asserts the contract.
        result = _run(f'_manifest_init "{tmp_path / "m.json"}"')
        assert result.returncode != 0
        assert "jq not found" in result.stderr
