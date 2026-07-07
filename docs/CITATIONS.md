# Citations: attribution, SME review, export, and source-type priority

*(Landed 2026-07-07 — approved plan `PLAN_citations_export_sme_review.md`; the
"chat UI vs dedicated review tool" question was settled by a deep-research pass:
MLflow's Review App is Databricks-gated, Argilla is in maintenance mode,
Label Studio/Langfuse would add a second service without two-sided span
highlighting — so the review surface lives in the chat app and feedback goes
straight to MLflow.)*

## 1. The attribution model (`harness/attribution.py`)

Claims are prompted (and schema-described) to be **verbatim spans** of the
answer. The server locates them — exact normalized match, then a fuzzy
`difflib` fallback — resolves overlaps, and numbers references **by first
appearance in the text**:

- `build_attribution(answer, citation_texts) -> Attribution`
  - `spans`: `[{start, end, refs}]` over the original answer string
  - `references`: numbered `[n]` entries = the citation + the **full** retrieved
    passage (joined by `chunk_id` in the adapter) + the quote located inside it
  - `unmatched_claims`: claims that could not be anchored (reported, never fatal)
- `Attribution.marked_text` — the answer with `[n]` markers injected after each
  attributed span; `to_dict()` — the JSON consumed by the review element and the
  HTML export.

Degradation is graceful: zero claims (or a model that ignores the verbatim rule
beyond fuzzy reach) yields the plain answer with score-ordered references —
exactly the pre-attribution behavior.

Provenance behind it: `HierarchicalPGRetriever` now surfaces the Document node's
`title / topic_path / committee / reference_number / source_type` plus a real
`chunk_id`, and every citation carries a **category** from
`harness/retrieval/doc_categories.py` (`scientific_guideline | qa | epar |
medicine_page | other`, classified from URL/topic path — there is no doc-type
property on the nodes).

## 2. In the chat

- The answer text carries clickable `[n]` markers (each is a Chainlit element
  reference opening that source card); the `**Sources:**` line lists every
  reference, anchored or not.
- Source cards show title, category, committee, reference number, score, URL.
- Under each answer: **🔍 Review citations (n)** — a persistent custom element
  (`public/elements/CitationReview.jsx`) that expands to a side-by-side view:
  answer with highlighted spans left, reference cards right (full passage with
  the retrieved quote highlighted). Click a span ⇄ its reference(s) highlight.

### SME feedback (per citation)

Each reference card offers **✓ supports / ~ partial / ✗ no**, an optional
*"wrong source type — prefer `<category>`"* select (the
EPAR-where-a-guideline-belongs case), and a free-text note. A verdict click:

1. logs one MLflow trace assessment via
   `harness.obs.log_citation_feedback` — unique name
   `citation_<rank>_<chunk8>`, `value=verdict`, `rationale=note`, metadata
   `{rank, chunk_id, doc_id, source_url, category, preferred_category, run_id}`
   (also visible/editable in the MLflow UI's trace **Assessments** panel);
2. persists the verdict into the element's props (`updateElement`), so reviewed
   state survives reloads and thread resume.

"Spot on" and ordering preferences are *derivable* (verdict × rank) — there is
deliberately no drag-to-reorder UI. `harness/export_traces.py` exports
`citation_ratings` alongside `step_ratings` for aggregation.

## 3. Export (`harness/export/`)

Per-turn **⬇ Export** (next to 👍/👎) renders the turn to the configured
formats and replies with downloadable files (persisted — downloads keep working
after resume; the bundle itself is session-held, so only current-session turns
can be re-exported).

- **markdown** — question, marked answer, confidence/judge, resolved `ema.*`
  config table, references with full passages (retrieved quote **bold**).
- **html** — one self-contained file (inline CSS/JS, no external requests):
  hover/click an answer span ⇄ its reference card highlights (both directions),
  quote highlighted inside each passage, config + judge sections, and the full
  bundle embedded as machine-readable JSON (`#ema-export-bundle`).

Config: `harness/configs/export/default.yaml`, loaded through the
`$EMA_CONFIG_DIR` search path (an external `export/default.yaml` shadows the
built-in). Unknown keys or unregistered formats are hard errors.

```yaml
export:
  formats: [markdown, html]     # names from the exporter registry
  include_config: true
  include_judge: true
  include_full_passages: true
  include_trace_link: true
  filename_template: "ema_answer_{msg_num}_{run8}"
```

### Adding an export format

```python
from harness.export import Exporter, register_exporter

@register_exporter("jsonl")
class JsonlExporter(Exporter):
    name, file_extension, mime = "jsonl", "jsonl", "application/jsonl"

    def render(self, bundle, options):
        import json
        return json.dumps(bundle.to_dict(), ensure_ascii=False)
```

then add `jsonl` to `formats:`. `ExportBundle.to_dict()` is the tool-neutral
interchange shape — if review volume ever outgrows 1–2 SMEs in the chat, a
dedicated annotation tool (Label Studio) can consume these bundles as tasks
with an assessments→MLflow sync, with no rework of the attribution/export
layers.

Programmatic: `harness.export.export_turn(bundle) -> [(filename, mime, content)]`.

## 4. Source-type priority (the feedback-tunable knob)

`doc_type_priority` is a deterministic node postprocessor
(`harness/retrieval/postprocessors.py`): stable-reorders retrieved nodes by
category priority (tie-break = retrieval order), so a recipe can guarantee
"guidelines before EPARs" today, without any learned model:

```yaml
# configs/retrieval/<pipeline>.yaml
retrieval:
  rerank: [doc_type_priority, cross_encoder]
  doc_type_priority: [scientific_guideline, qa, epar]   # validated categories
```

The per-citation SME feedback (§2) accumulates exactly the data needed to tune
this order — or to justify a learned re-ranker later (deferred per the
complexity rule).

## 5. Runtime verification (GPU host)

Live turn → `[n]` markers clickable; **Review citations** expands, verdict click
lands as a `citation_*` assessment on the trace; **⬇ Export** produces MD+HTML
downloads whose highlight sync works in a browser; resume the thread → review
element still present with saved verdicts.
