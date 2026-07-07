"""Unit tests for harness.export (registry, options, bundle, MD/HTML renderers)."""

import json

import pytest

from harness.attribution import build_attribution
from harness.export import (
    ExportBundle,
    Exporter,
    ExportOptions,
    export_turn,
    get_exporter,
    list_exporters,
    load_export_options,
    register_exporter,
)
from harness.schemas import Citation, Claim, RegulatoryAnswer

FULL = "Background context. The Acceptable Intake for NDMA is 96 ng/day. Trailing text."


def _bundle() -> ExportBundle:
    answer = RegulatoryAnswer(
        answer="The Acceptable Intake for NDMA is 96 ng/day.",
        claims=[
            Claim(
                text="The Acceptable Intake for NDMA is 96 ng/day.",
                citations=[Citation(source_url="https://ema.eu/n", chunk_id="c1")],
            )
        ],
        citations=[
            Citation(
                source_url="https://ema.eu/n", chunk_id="c1", title="Nitrosamines Q&A",
                committee="CHMP", reference_number="EMA/409815/2020", category="qa",
                quote="Acceptable Intake for NDMA is 96 ng/day", score=0.91,
            )
        ],
        confidence=0.9,
        caveats=["Applies to human medicinal products."],
    )
    return ExportBundle(
        question="What is the AI for NDMA?",
        answer=answer,
        attribution=build_attribution(answer, [FULL]),
        recipe_name="naive_rag",
        resolved_config={"ema.recipe": "naive_rag", "ema.generation.model": "claude_opus"},
        settings={"model": "claude_opus"},
        judge_results=[{"name": "faithfulness", "score": 4, "rationale": "grounded"}],
        confidence=0.9,
        run_id="run-123456789",
        trace_id="tr-1",
        trace_url="http://localhost:5000/#/traces?x=1",
        msg_num=3,
        asked_at="2026-07-07T09:00:00",
    )


# ── registry + options ────────────────────────────────────────────────────────

def test_builtin_exporters_registered():
    assert list_exporters() == ["html", "markdown"]


def test_get_unknown_exporter_raises():
    with pytest.raises(ValueError, match="Unknown exporter"):
        get_exporter("pdf")


def test_duplicate_register_raises():
    with pytest.raises(ValueError, match="already registered"):

        @register_exporter("markdown")
        class _Dup(Exporter):  # pragma: no cover - registration fails first
            def render(self, bundle, options):
                return ""


def test_options_reject_unknown_key_and_unregistered_format():
    with pytest.raises(ValueError, match="Unknown export option"):
        ExportOptions.from_dict({"formatz": ["markdown"]})
    with pytest.raises(ValueError, match="unregistered exporter"):
        ExportOptions.from_dict({"formats": ["markdown", "docx"]})


def test_load_default_export_config():
    options = load_export_options()
    assert options.formats == ["markdown", "html"]
    assert options.include_full_passages is True


def test_load_export_options_honors_ema_config_dir(tmp_path, monkeypatch):
    (tmp_path / "export").mkdir()
    (tmp_path / "export" / "default.yaml").write_text(
        "export:\n  formats: [markdown]\n  include_config: false\n", encoding="utf-8"
    )
    monkeypatch.setenv("EMA_CONFIG_DIR", str(tmp_path))
    options = load_export_options()
    assert options.formats == ["markdown"] and options.include_config is False


# ── renderers ────────────────────────────────────────────────────────────────

def test_markdown_export_contains_all_sections():
    md = get_exporter("markdown").render(_bundle(), ExportOptions())
    assert md.startswith("# What is the AI for NDMA?")
    assert "96 ng/day. [1]" in md                      # marked answer
    assert "## Configuration" in md and "`ema.recipe`" in md
    assert "### [1] Nitrosamines Q&A" in md
    assert "committee `CHMP`" in md and "ref `EMA/409815/2020`" in md
    assert "**Acceptable Intake for NDMA is 96 ng/day**" in md  # quote bolded in passage
    assert "faithfulness 4/5" in md
    assert "[View trace →](http://localhost:5000" in md


def test_markdown_respects_option_toggles():
    options = ExportOptions(include_config=False, include_judge=False,
                            include_full_passages=False, include_trace_link=False)
    md = get_exporter("markdown").render(_bundle(), options)
    assert "## Configuration" not in md
    assert "faithfulness" not in md
    assert "Background context." not in md   # quotes only
    assert "View trace" not in md


def test_html_export_selfcontained_with_highlight_sync():
    html = get_exporter("html").render(_bundle(), ExportOptions())
    assert html.startswith("<!doctype html>")
    assert '<mark class="span" data-refs="1">' in html          # answer span
    assert 'id=\'ref-1\'' in html                               # reference card
    assert '<mark class="quote">' in html                       # quote inside passage
    assert "addEventListener" in html                           # sync JS inlined
    assert "http://" not in html.replace("http://localhost:5000", "").replace(
        "https://ema.eu/n", ""
    )  # no external fetches beyond the cited URL + trace link
    # the machine-readable bundle is embedded and parseable
    start = html.index("id='ema-export-bundle'>") + len("id='ema-export-bundle'>")
    end = html.index("</script>", start)
    embedded = json.loads(html[start:end])
    assert embedded["question"] == "What is the AI for NDMA?"
    assert embedded["attribution"]["references"][0]["n"] == 1


def test_export_turn_returns_all_configured_formats():
    files = export_turn(_bundle())
    names = [f[0] for f in files]
    assert names == ["ema_answer_3_run-1234.md", "ema_answer_3_run-1234.html"]
    assert files[0][1] == "text/markdown" and files[1][1] == "text/html"
    assert all(content for _, _, content in files)
