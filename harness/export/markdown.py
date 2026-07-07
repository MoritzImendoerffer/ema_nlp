"""Markdown exporter: query + config + marked answer + full references."""

from __future__ import annotations

from harness.export.base import Exporter, ExportOptions
from harness.export.bundle import ExportBundle
from harness.export.registry import register_exporter


def _bold_quote(passage: str, start: int, end: int) -> str:
    """Bold the retrieved-quote region inside the full passage (when located)."""
    if 0 <= start < end <= len(passage):
        return f"{passage[:start]}**{passage[start:end]}**{passage[end:]}"
    return passage


@register_exporter("markdown")
class MarkdownExporter(Exporter):
    name = "markdown"
    file_extension = "md"
    mime = "text/markdown"

    def render(self, bundle: ExportBundle, options: ExportOptions) -> str:
        att = bundle.attribution
        lines: list[str] = [f"# {bundle.question}", ""]
        meta_bits = [b for b in (
            bundle.asked_at,
            f"recipe `{bundle.recipe_name}`" if bundle.recipe_name else "",
            f"run `{bundle.run_id[:8]}`" if bundle.run_id else "",
        ) if b]
        if meta_bits:
            lines += ["*" + " · ".join(meta_bits) + "*", ""]

        lines += ["## Answer", "", att.marked_text, ""]
        if bundle.confidence is not None:
            lines.append(f"**Model confidence:** {bundle.confidence:.2f}")
        if options.include_judge and bundle.judge_results:
            judged = ", ".join(
                f"{j.get('name', '?')} {j.get('score', '?')}/5" for j in bundle.judge_results
            )
            lines.append(f"**Judge:** {judged}")
        if bundle.answer.caveats:
            lines += ["", "**Caveats:**"] + [f"- {c}" for c in bundle.answer.caveats]
        if att.unmatched_claims:
            lines += ["", "**Unanchored claims** (not locatable verbatim in the answer):"]
            lines += [f"- {c}" for c in att.unmatched_claims]
        lines.append("")

        if options.include_config and bundle.resolved_config:
            lines += ["## Configuration", "", "| key | value |", "|---|---|"]
            for key in sorted(bundle.resolved_config):
                lines.append(f"| `{key}` | `{bundle.resolved_config[key]}` |")
            lines.append("")

        lines += ["## References", ""]
        for ref in att.references:
            cit = ref.citation
            title = cit.title or cit.source_url or "Source"
            lines.append(f"### [{ref.n}] {title}")
            detail = [f"category `{cit.category or '—'}`"]
            if cit.committee:
                detail.append(f"committee `{cit.committee}`")
            if cit.reference_number:
                detail.append(f"ref `{cit.reference_number}`")
            if cit.score is not None:
                detail.append(f"score `{cit.score:.3f}`")
            lines.append(" · ".join(detail) + "  ")
            if cit.source_url:
                lines.append(f"Source: <{cit.source_url}>")
            lines.append("")
            passage = ref.full_text if options.include_full_passages else cit.quote
            if passage:
                if passage == ref.full_text:
                    passage = _bold_quote(passage, ref.quote_start, ref.quote_end)
                lines += ["> " + line for line in passage.splitlines()] or []
                lines.append("")

        if options.include_trace_link and bundle.trace_url:
            lines += [f"[View trace →]({bundle.trace_url})", ""]
        return "\n".join(lines)
