"""Self-contained HTML exporter with two-way span↔reference highlighting.

One file, inline CSS + JS, no external requests — opens anywhere offline.
Hovering/clicking an attributed answer span highlights its reference card(s)
(and scrolls the first into view); clicking a reference highlights every answer
span it supports. The retrieved quote is highlighted inside each full passage.
"""

from __future__ import annotations

import html as html_mod
import json

from harness.export.base import Exporter, ExportOptions
from harness.export.bundle import ExportBundle
from harness.export.registry import register_exporter

_CSS = """
:root { --accent: #2456a3; --mark: #fff3bf; --mark-active: #ffd43b;
        --quote: #d3f9d8; --border: #d0d7de; color-scheme: light; }
* { box-sizing: border-box; }
body { font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
       margin: 0 auto; max-width: 60rem; padding: 2rem 1.25rem 4rem; color: #1f2328; }
h1 { font-size: 1.5rem; line-height: 1.3; }
h2 { font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid var(--border);
     padding-bottom: .3rem; }
.meta { color: #57606a; font-size: .85rem; }
mark.span { background: var(--mark); padding: .05em 0; border-radius: 2px; cursor: pointer; }
mark.span.active { background: var(--mark-active); }
a.marker { color: var(--accent); font-weight: 600; text-decoration: none;
           font-size: .8em; vertical-align: super; margin-left: .1em; }
.answer { white-space: pre-wrap; }
.ref { border: 1px solid var(--border); border-radius: 8px; padding: .9rem 1rem;
       margin: .8rem 0; }
.ref.active { border-color: var(--accent); box-shadow: 0 0 0 2px #2456a333; }
.ref h3 { margin: 0 0 .3rem; font-size: 1rem; cursor: pointer; }
.ref .detail { color: #57606a; font-size: .82rem; margin-bottom: .5rem; }
.ref .passage { white-space: pre-wrap; font-size: .9rem; background: #f6f8fa;
                border-radius: 6px; padding: .6rem .75rem; max-height: 16rem;
                overflow-y: auto; }
mark.quote { background: var(--quote); }
.badge { display: inline-block; border: 1px solid var(--border); border-radius: 999px;
         padding: 0 .5em; font-size: .75rem; }
table { border-collapse: collapse; font-size: .85rem; }
td, th { border: 1px solid var(--border); padding: .25rem .6rem; text-align: left; }
.caveat { color: #9a6700; }
"""

_JS = """
function activate(refs) {
  document.querySelectorAll('.ref, mark.span').forEach(el => el.classList.remove('active'));
  refs.forEach(n => {
    const card = document.getElementById('ref-' + n);
    if (card) card.classList.add('active');
    document.querySelectorAll('mark.span').forEach(el => {
      if (el.dataset.refs.split(' ').includes(String(n))) el.classList.add('active');
    });
  });
  const first = document.getElementById('ref-' + refs[0]);
  if (first) first.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}
document.querySelectorAll('mark.span').forEach(el =>
  el.addEventListener('click', () => activate(el.dataset.refs.split(' ').map(Number))));
document.querySelectorAll('.ref h3').forEach(el =>
  el.addEventListener('click', () => activate([Number(el.closest('.ref').dataset.ref)])));
"""


def _esc(text: str) -> str:
    return html_mod.escape(text, quote=True)


def _answer_html(attribution) -> str:
    """Answer text with escaped segments, <mark> spans, and [n] marker links."""
    text = attribution.answer_text
    parts: list[str] = []
    cursor = 0
    for span in sorted(attribution.spans, key=lambda s: s.start):
        parts.append(_esc(text[cursor : span.start]))
        refs = sorted(set(span.ref_ns))
        refs_attr = " ".join(str(n) for n in refs)
        parts.append(f'<mark class="span" data-refs="{refs_attr}">{_esc(text[span.start : span.end])}</mark>')
        parts.extend(
            f'<a class="marker" data-ref="{n}" href="#ref-{n}">[{n}]</a>' for n in refs
        )
        cursor = span.end
    parts.append(_esc(text[cursor:]))
    return "".join(parts)


def _passage_html(ref, include_full: bool) -> str:
    passage = ref.full_text if include_full else ref.citation.quote
    if not passage:
        return ""
    if include_full and 0 <= ref.quote_start < ref.quote_end <= len(passage):
        body = (
            _esc(passage[: ref.quote_start])
            + f'<mark class="quote">{_esc(passage[ref.quote_start : ref.quote_end])}</mark>'
            + _esc(passage[ref.quote_end :])
        )
    else:
        body = _esc(passage)
    return f'<div class="passage">{body}</div>'


@register_exporter("html")
class HtmlExporter(Exporter):
    name = "html"
    file_extension = "html"
    mime = "text/html"

    def render(self, bundle: ExportBundle, options: ExportOptions) -> str:
        att = bundle.attribution
        parts: list[str] = [
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            f"<title>{_esc(bundle.question[:120])}</title>",
            f"<style>{_CSS}</style></head><body>",
            f"<h1>{_esc(bundle.question)}</h1>",
        ]
        meta_bits = [b for b in (
            bundle.asked_at,
            f"recipe {bundle.recipe_name}" if bundle.recipe_name else "",
            f"run {bundle.run_id[:8]}" if bundle.run_id else "",
        ) if b]
        if meta_bits:
            parts.append(f"<p class='meta'>{_esc(' · '.join(meta_bits))}</p>")

        parts.append("<h2>Answer</h2>")
        parts.append(f"<div class='answer'>{_answer_html(att)}</div>")

        info_bits: list[str] = []
        if bundle.confidence is not None:
            info_bits.append(f"Model confidence {bundle.confidence:.2f}")
        if options.include_judge:
            info_bits += [
                f"{_esc(str(j.get('name', '?')))} {_esc(str(j.get('score', '?')))}/5"
                for j in bundle.judge_results
            ]
        if info_bits:
            parts.append(f"<p class='meta'>{' · '.join(info_bits)}</p>")
        for caveat in bundle.answer.caveats:
            parts.append(f"<p class='caveat'>⚠ {_esc(caveat)}</p>")
        if att.unmatched_claims:
            parts.append(
                "<p class='meta'>Unanchored claims (not locatable verbatim in the answer): "
                + "; ".join(_esc(c) for c in att.unmatched_claims)
                + "</p>"
            )

        if options.include_config and bundle.resolved_config:
            parts.append("<h2>Configuration</h2><table>")
            for key in sorted(bundle.resolved_config):
                parts.append(
                    f"<tr><td><code>{_esc(str(key))}</code></td>"
                    f"<td><code>{_esc(str(bundle.resolved_config[key]))}</code></td></tr>"
                )
            parts.append("</table>")

        parts.append("<h2>References</h2>")
        for ref in att.references:
            cit = ref.citation
            title = cit.title or cit.source_url or "Source"
            detail_bits = [f"<span class='badge'>{_esc(cit.category or 'other')}</span>"]
            if cit.committee:
                detail_bits.append(_esc(cit.committee))
            if cit.reference_number:
                detail_bits.append(_esc(cit.reference_number))
            if cit.score is not None:
                detail_bits.append(f"score {cit.score:.3f}")
            link = (
                f"<a href='{_esc(cit.source_url)}'>{_esc(cit.source_url)}</a>"
                if cit.source_url
                else ""
            )
            parts.append(
                f"<article class='ref' id='ref-{ref.n}' data-ref='{ref.n}'>"
                f"<h3>[{ref.n}] {_esc(title)}</h3>"
                f"<div class='detail'>{' · '.join(detail_bits)}<br>{link}</div>"
                f"{_passage_html(ref, options.include_full_passages)}</article>"
            )

        if options.include_trace_link and bundle.trace_url:
            parts.append(f"<p><a href='{_esc(bundle.trace_url)}'>View trace →</a></p>")

        # Machine-readable copy of the bundle for downstream tooling (Label Studio
        # fallback path): same interchange dict the SME element consumes.
        parts.append(
            "<script type='application/json' id='ema-export-bundle'>"
            + json.dumps(bundle.to_dict(), ensure_ascii=False).replace("</", "<\\/")
            + "</script>"
        )
        parts.append(f"<script>{_JS}</script></body></html>")
        return "".join(parts)
