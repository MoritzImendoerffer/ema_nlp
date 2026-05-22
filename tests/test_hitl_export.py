"""
Unit tests for harness/hitl/export_annotations.py.

Uses unittest.mock to avoid needing a live Phoenix instance.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_SPANS = [
    {
        "context": {"trace_id": "trace1", "span_id": "span1"},
        "name": "think",
        "attributes": {
            "input.value": "What is NDMA AI?",
            "output.value": "Thought: search first.",
            "workflow_name": "react",
        },
    },
    {
        "context": {"trace_id": "trace1", "span_id": "span2"},
        "name": "act",
        "attributes": {
            "input.value": "ema_search NDMA",
            "output.value": "Found 3 docs.",
            "workflow_name": "react",
        },
    },
    {
        "context": {"trace_id": "trace2", "span_id": "span3"},
        "name": "think",
        "attributes": {
            "input.value": "What is ASMF?",
            "output.value": "Thought: search.",
            "workflow_name": "crag",
        },
    },
]

_FAKE_ANNOTATIONS = {
    "span1": [
        {
            "span_id": "span1",
            "name": "step_quality",
            "result": {"label": "good", "explanation": "Correct tool call"},
            "annotator_kind": "HUMAN",
            "updated_at": "2026-05-23T10:00:00Z",
        }
    ],
    "span2": [
        {
            "span_id": "span2",
            "name": "step_quality",
            "result": {"label": "suboptimal"},
            "annotator_kind": "HUMAN",
            "updated_at": "2026-05-23T10:05:00Z",
        }
    ],
    # span3 has no annotations — should not appear in output
}


def _make_fake_get_json(spans=_FAKE_SPANS, annotation_map=_FAKE_ANNOTATIONS):
    """Return a _get_json replacement that serves fake span + annotation data."""
    def _fake(url: str, timeout: int = 30):
        if "/v1/spans" in url:
            return {"data": spans}
        if "/v1/span_annotations" in url:
            # Collect span_ids from query string
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(url).query)
            requested_ids = qs.get("span_id", [])
            anns = []
            for sid in requested_ids:
                anns.extend(annotation_map.get(sid, []))
            return {"data": anns}
        return {"data": []}
    return _fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildRecord:
    def test_extracts_label_and_reason(self):
        from harness.hitl.export_annotations import _build_record
        span = _FAKE_SPANS[0]
        anns = _FAKE_ANNOTATIONS["span1"]
        rec = _build_record(span, anns)
        assert rec["span_id"] == "span1"
        assert rec["span_name"] == "think"
        assert rec["labels"]["step_quality"] == "good"
        assert "Correct tool call" in rec["reason"]

    def test_no_annotations_yields_empty_labels(self):
        from harness.hitl.export_annotations import _build_record
        span = _FAKE_SPANS[0]
        rec = _build_record(span, [])
        assert rec["labels"] == {}
        assert rec["scores"] == {}
        assert rec["reason"] is None

    def test_score_annotation_parsed(self):
        from harness.hitl.export_annotations import _build_record
        span = _FAKE_SPANS[0]
        ann = {"span_id": "span1", "name": "answer_quality",
               "result": {"score": 4.0}, "annotator_kind": "HUMAN", "updated_at": ""}
        rec = _build_record(span, [ann])
        assert rec["scores"]["answer_quality"] == pytest.approx(4.0)


class TestExport:
    def test_dry_run_returns_only_annotated_spans(self, capsys):
        from harness.hitl.export_annotations import export
        with patch("harness.hitl.export_annotations._get_json", side_effect=_make_fake_get_json()):
            records = export("2026-05-20", dry_run=True)

        # span3 has no annotations — should not be in output
        span_ids = [r["span_id"] for r in records]
        assert "span1" in span_ids
        assert "span2" in span_ids
        assert "span3" not in span_ids

    def test_dry_run_prints_json_lines(self, capsys):
        from harness.hitl.export_annotations import export
        with patch("harness.hitl.export_annotations._get_json", side_effect=_make_fake_get_json()):
            export("2026-05-20", dry_run=True)

        out = capsys.readouterr().out
        lines = [l for l in out.strip().split("\n") if l]
        for line in lines:
            parsed = json.loads(line)
            assert "span_id" in parsed

    def test_writes_jsonl_file(self, tmp_path):
        from harness.hitl.export_annotations import export
        with patch("harness.hitl.export_annotations._get_json", side_effect=_make_fake_get_json()):
            records = export("2026-05-20", out_dir=tmp_path)

        # File named YYYY-MM-DD.jsonl
        written = list(tmp_path.glob("*.jsonl"))
        assert len(written) == 1
        lines = written[0].read_text().strip().split("\n")
        assert len(lines) == len(records)
        for line in lines:
            row = json.loads(line)
            assert "span_id" in row
            assert "labels" in row

    def test_strategy_filter_forwarded(self):
        """Strategy kwarg is passed through; server-side filtering is assumed."""
        from harness.hitl.export_annotations import export
        calls: list[str] = []

        def recording_get(url, **kw):
            calls.append(url)
            return _make_fake_get_json()(url)

        with patch("harness.hitl.export_annotations._get_json", side_effect=recording_get):
            export("2026-05-20", strategy="react", dry_run=True)

        span_call = next(u for u in calls if "/v1/spans" in u)
        assert "react" in span_call

    def test_unreachable_phoenix_raises_runtime_error(self):
        from harness.hitl.export_annotations import _get_json
        from urllib.error import URLError

        # Patch urlopen so _get_json's own error handler runs
        with patch("harness.hitl.export_annotations.urlopen", side_effect=URLError("Connection refused")):
            with pytest.raises(RuntimeError, match="Cannot reach Phoenix"):
                _get_json("http://localhost:6006/v1/spans")

    def test_output_schema_has_required_fields(self, tmp_path):
        required = {"trace_id", "span_id", "span_name", "input", "output",
                    "labels", "scores", "reason", "annotated_by", "annotated_at"}
        from harness.hitl.export_annotations import export
        with patch("harness.hitl.export_annotations._get_json", side_effect=_make_fake_get_json()):
            records = export("2026-05-20", dry_run=True)

        for rec in records:
            assert required <= set(rec.keys()), f"Missing keys in {rec}"
