# Citation attribution, SME review, and configurable export — refined plan

*(v2, 2026-07-05 — refined after a 103-agent deep-research pass on the "chat UI vs dedicated
review tool" question; 19 adversarially-verified claims, sources cited inline.)*

## 1. Context

Two loosely-coupled asks (owner):

1. **Export** a chat turn as Markdown + HTML — config-driven, extensible by subclassing;
   containing the query, the resolved configuration, the answer **with citations**, and all
   references. HTML export should highlight the answer span attributable to each reference
   *and* highlight the reference itself. Chat text must also cite references inline.
2. **SME citation verification** (the priority): quickly compare answer text against cited
   sources — side-by-side with highlight sync — and rate citations (supports / partial /
   wrong source type, e.g. "high-score EPAR where a guideline should be cited first"),
   feeding a future re-ranking loop.

## 2. The researched question: extend the chat UI, or adopt a dedicated review tool?

**Verdict: build the review UI inside the existing Chainlit app; write per-citation
feedback straight to MLflow.** It is the only option satisfying every hard constraint
(self-hosted, SQLite MLflow as system of record, per-citation metadata, two-sided span
highlighting, minimal new infrastructure). Evidence:

| Option | Finding (confidence) | Why it loses / wins |
|---|---|---|
| **MLflow native (C)** | Review App + labeling sessions are **Databricks-gated at the code level** (`labeling store registers only the 'databricks' URI scheme; other URIs raise UnsupportedLabelingStoreURIException`) and even there are **trace-level only** — no per-citation granularity (high, 9-0) | Not available on our SQLite MLflow; marketing pages blur this. |
| **MLflow OSS APIs (C, partial)** | `mlflow.log_feedback()` in OSS 3.x supports `trace_id, name, value, AssessmentSource, rationale, metadata,` **`span_id`** — the exact pattern already runtime-verified in `harness/obs/tracing.py` (high, 6-0). OSS UI has an **Assessments panel** on the trace view since 3.2/3.3 (high, 3-0) | **We use this as the storage + secondary read surface**: per-citation assessments become visible/editable in the MLflow UI we already run. |
| **Label Studio (B)** | Official "Evaluate RAG with Human Feedback" template is the closest ready-made artifact, but: two-bucket relevant/non-relevant only, **no span highlighting on either side**, no per-passage notes, vertical layout — meeting the spec means custom XML + a new always-on service + an annotations→MLflow sync script (high, 9-0) | Comparable build effort (~2–4d) **plus** permanent second service + sync pipeline; still no two-sided span highlighting out of the box. |
| **Argilla (B)** | **Maintenance mode** — authors stopped feature development, bug fixes only, publicly seeking maintainers; last release v2.8.0 (Mar 2025) (high, 6-0) | Adoption risk rules it out for a new workflow. |
| **Langfuse (B)** | Annotation queues genuinely free in the MIT self-hosted tier; annotations attach to traces/observations — but **no citation/span UI**, and adoption = standing up a **second tracing backend parallel to MLflow** + sync job (high, 11-1) | Directly against the project's deliberate consolidation on MLflow after removing Phoenix. |
| **Chainlit CustomElement (A)** | Feasible without forking: JSX in `public/elements/`, whitelisted imports (react, shadcn `@/components/ui/*`, zod, lucide-react — **no arbitrary npm**), injected `callAction`/`updateElement` APIs, `inline/side/page` display (high, 9-0). Estimated **~3–5 dev-days** for the review panel | **Winner.** Zero new infrastructure; the SME reviews in the same surface where the answer appears; feedback lands in MLflow directly. Persistence caveat (#2576/#1799: elements vanish without a persistence layer) is **already solved** — our `_LocalStorageClient` fix (commit `926487d`). |

**Revisit trigger (documented, not built):** if review ever needs multi-annotator queues /
inter-annotator agreement, the fallback is Label Studio consuming the **export bundle**
(§5) as its task format with an assessments→MLflow sync — the bundle is deliberately
designed as a tool-neutral interchange JSON so that path requires no rework of stages 1–3.

## 3. Design decisions

- **D1 Attribution = verbatim claims + server-derived markers.** Prompt + Pydantic field
  descriptions require each `Claim.text` to be a verbatim span of `answer`; the server
  matches spans (exact-normalized → fuzzy) and injects `[n]` markers. One attribution model
  powers chat, HTML export, and the SME view. Degrades gracefully: unmatched claims listed
  unhighlighted; zero claims → answer-level citations (today's behavior). *(Alternative —
  LLM-emitted markers — rejected: point anchors only, no span highlighting, depends on model
  numbering discipline over ephemeral per-tool-call labels.)*
- **D2 SME view = persistent CustomElement per answer** (research-confirmed, §2): collapsed
  "🔍 Review citations (n)" row under each answer → expandable side-by-side panel. Attached
  to the message ⇒ survives chat resume (actions/sidebar don't).
- **D3 Feedback taxonomy** per reference: (a) grounding verdict `supports | partial | no`,
  (b) `wrong source type — prefer <category>` flag (the EPAR-vs-guideline case), (c) optional
  note. Logged via `mlflow.log_feedback` with **`span_id` of the retrieval span** when
  available + metadata `{rank, chunk_id, doc_id, source_url, category, preferred_category}`.
  "Spot on" and ordering preferences are **derivable** (verdict × rank) — no drag-reorder UI.
  Plus a **deterministic doc-type priority reranker** as the config knob this feedback later
  tunes; learned re-ranking deferred until data accumulates (complexity rule).
- **D4 Export scope = per-turn, full detail** (MD + HTML, full passages). Current-session
  turns only (bundles are session-held); generated files persist via the storage client and
  stay downloadable after resume. Whole-conversation export deferred.

## 4. Current-state facts the plan builds on (verified in-repo)

- `Citation = {source_url, doc_id, chunk_id, quote(240ch), score}`; **no field descriptions
  exist anywhere** (steering gap); `chunk_id` empty on the live path.
- Claims are free-form paraphrases today (tests pin non-verbatim); the agent sees only
  ephemeral `[i] source=<url>` per tool call (`harness/tools/search.py:format_nodes`) and
  cannot cite stable ids; `coerce_answer` rebuilds citations from captured nodes and
  enriches claim citations by URL join (`harness/agents/runner.py`).
- `title, topic_path, committee, reference_number, source_type` exist on Neo4j Document
  nodes but are **not selected** by `HierarchicalPGRetriever._QUERY`
  (`harness/indexing/property_graph.py:498`). No doc-type property stored → EPAR vs
  guideline must be classified from URL/topic_path.
- Full untruncated passages already flow as `result["context_passages"]`.
- Chainlit 2.11.1: CustomElement persists when attached to a message (with our storage
  client); `unsafe_allow_html=false` ⇒ HTML export must be a **download** (`cl.File`,
  persisted, needs `for_id` ⇒ attach to a message). Export capture point: end of
  `app.py:_run_pipeline` (~line 825) — everything needed is in scope; nothing per-turn is
  retained today beyond `last_run_id`/`last_trace_id`.
- House patterns to mirror: decorator registry (`harness/tools/registry.py`), config
  namespace via `find_config` + `$EMA_CONFIG_DIR` (recipes/index precedent), `from_dict`
  with hard `ValueError` (F10), postprocessor seam
  (`harness/retrieval/postprocessors.py` → recipe `rerank:` list).

## 5. Implementation stages

### Stage 1 — Attribution foundation *(~1.5 days; everything else consumes this)*

**1a. Enrich retrieval metadata** — `harness/indexing/property_graph.py`
- Extend `_QUERY` RETURN with `d.title, d.topic_path, d.committee, d.reference_number,
  d.source_type`; meta dict gains those keys; set `chunk_id` = returned node id (fixes the
  empty-chunk_id gap). Offline test via faked `structured_query` rows.

**1b. Source-category classifier** — new `harness/retrieval/doc_categories.py`
- Pure, table-driven `classify_source(source_url, topic_path) -> scientific_guideline | qa
  | epar | medicine_page | other` (EMA URL-tree heuristics; extensible). Tests on real
  corpus URLs.

**1c. Citation schema + prompts** — `harness/schemas/answer.py`, `harness/prompts/agent_*.md`
- `Citation` gains `title, topic_path, committee, reference_number, source_type, category`;
  populated in `citation_from_node`. **Add `Field(description=…)` to every
  Citation/Claim/RegulatoryAnswer field** (none exist — they steer the LLM).
  `Claim.text`: *"a verbatim, contiguous quote copied exactly from `answer` — no
  paraphrasing."* All four agent prompts updated accordingly.

**1d. Attribution model** — new `harness/attribution.py` (pure, heavily tested)
- `match_spans(answer, claims)`: normalized exact match (casefold/whitespace with offset
  map) → `difflib.SequenceMatcher` sliding-window fallback (ratio ≥ 0.85); overlap
  resolution (longer, then earlier).
- `build_attribution(answer, references) -> Attribution`: `answer_text`,
  `spans[{start,end,ref_indices}]`, `references[{n, citation fields, full_text,
  quote_start, quote_end}]` (quote located inside the full passage for reference-side
  highlighting), `unmatched_claims`. Numbering = first appearance in text; unreferenced
  citations appended. `to_dict()` = the shared JSON for JSX props + HTML export.
- `render_markers(attribution)`: answer text with `[n]` injected after each span.

**1e. Adapter emits references** — `harness/agents/workflow_adapter.py`
- Join `answer.citations` ↔ captured nodes (chunk_id/node id; positional fallback) →
  result gains `"references"` and `"attribution"`. Also capture the **retrieval span id**
  per turn where obtainable (for `span_id`-scoped feedback). Existing keys unchanged.

### Stage 2 — Inline citations in the chat *(~0.5 day)*

- `app.py`: source elements renamed `[1]`…`[n]` (attribution numbering) — Chainlit renders
  each occurrence of an element *name* in the message text as a clickable pill, so the
  injected `[n]` markers themselves become clickable citations opening the source card.
- Message = `render_markers(...)` + judge/confidence note + `**Sources:** [1] <title> · …`
  line (keeps unanchored citations reachable). Cards enriched: title, category badge,
  committee, reference number, score, URL. Zero-claims fallback = today's behavior.

### Stage 3 — Export subsystem *(~1.5 days)*

New package `harness/export/` (mirrors tools-registry style):
- `registry.py`: `@register_exporter(name)` (duplicate-guard `ValueError`), `get_exporter`
  ("Available: …"), `list_exporters`.
- `base.py`: `Exporter` ABC — `name/file_extension/mime`, `render(bundle, options) -> str`.
  **Subclass + register = the extension story (ask 1a)**; documented with an example.
- `bundle.py`: `ExportBundle` dataclass — question, asked_at, recipe_name, resolved
  `ema.*` config, settings overrides, answer, attribution, references, judge results,
  confidence, run_id, trace_id, msg_num; `to_dict()`. Built at the end of `_run_pipeline`,
  stashed in `cl.user_session["turn_bundles"][run_id]`. **This dict is the tool-neutral
  interchange format** (Label Studio fallback path consumes it unchanged).
- `markdown.py`: question → marked answer → confidence/judge → config section →
  references (`[n] title — url`, metadata line, full passage blockquote with the retrieved
  quote **bold**).
- `html.py`: one self-contained file (inline CSS+JS, no CDN, works offline): answer with
  `<mark data-refs>` spans; hover/click span ⇄ reference card highlight (both directions);
  reference cards show metadata + full passage with the quoted region highlighted; config +
  judge sections. Python-string template with embedded attribution JSON — no new deps.
- Config: `harness/configs/export/default.yaml` → `ExportOptions.from_dict` (hard
  `ValueError` on unknown formats/keys): `formats: [markdown, html]`,
  `include_config/judge/full_passages/trace_link`, `filename_template`. Loaded via
  `find_config("export", …)` ⇒ `$EMA_CONFIG_DIR` override for free.
- UI: "⬇ Export" `cl.Action` per answer (payload `run_id`) → callback renders enabled
  formats → reply message with `cl.File` elements (persisted ⇒ downloads survive resume).
  Pre-resume turns not exportable (bundles are session-held) — documented.
- Programmatic API: `harness.export.export_turn(bundle, formats=None, options=None)`.

### Stage 4 — SME review CustomElement + per-citation feedback *(~2–3 days; research-estimated 3–5 incl. Stage 1's span work)*

- **`public/elements/CitationReview.jsx`** — self-contained React within Chainlit's
  whitelist (react + shadcn `@/components/ui/*` + lucide only; no external npm; Tailwind
  color subset): collapsed header row → expanded two-pane: left = answer with highlighted
  spans; right = reference cards (n, title, category badge, committee, ref number, score,
  URL, full passage with quote highlighted). Hover/click sync both directions.
  Per-reference controls: `✓ supports / ~ partial / ✗ no` + "prefer <category>" select +
  note → `callAction({name: "cite_feedback", payload})`; verdict state written back via
  `updateElement(props)` so it persists visually across reload/resume.
- **`app.py`**: attach `cl.CustomElement(name="CitationReview", props=attribution dict +
  {run_id, trace_id, retrieval span ids}, display="inline")` to the answer message
  (message-attached ⇒ persists). New `@cl.action_callback("cite_feedback")`.
- **`harness/obs/tracing.py`**: `log_citation_feedback(trace_id, *, rank, verdict,
  chunk_id, doc_id, source_url, category, preferred_category=None, note=None, run_id,
  span_id=None)` → `_log_feedback` with unique `name=f"citation_{rank}_{chunk8}"`,
  `value=verdict`, `rationale=note`, metadata dict, **`span_id`** when available. SME
  feedback is then also visible/editable in MLflow's own trace **Assessments panel** (OSS
  3.2+) — a free second review surface. `export_traces.py` gains `citation_*` readback
  (mirrors its existing `step_quality` handling) for future aggregation.
- `query_cache.CacheEntry` extension deferred until few-shot needs per-citation ratings.

### Stage 5 — Deterministic doc-type priority reranker *(~0.5 day)*

- `@register_postprocessor("doc_type_priority")` in `harness/retrieval/postprocessors.py`:
  stable reorder by category priority (via `doc_categories.classify_source` on node
  metadata), tie-break by score; no heavy deps.
- `RetrievalPipelineConfig` gains optional `doc_type_priority: list[str]` (validated, hard
  error on unknown categories); selectable via a recipe pipeline's `rerank:` list; stamped
  honestly via existing `resolved_attributes`. This is the knob the Stage-4 feedback will
  eventually tune — learned re-ranking stays deferred.

### Stage 6 — Docs + housekeeping *(~0.5 day)*

- New `docs/CITATIONS.md`: attribution model, inline markers, SME review + feedback
  taxonomy, export how-to (incl. subclass-an-exporter example), reranker knob, the
  tool-comparison verdict + Label-Studio fallback trigger. CLAUDE.md banner (📎);
  cross-link from `docs/RECIPES.md`.
- `DECISIONS.md`: D1 (verbatim-claim attribution), D2+research verdict (in-chat SME review
  over dedicated tools — with the Databricks-gating/maintenance-mode/second-backend
  evidence), D3 (feedback taxonomy + deterministic reranker now, learned later).
- `docs/REQUIREMENTS_REVIEW.md` decision-log rows (extends R5); `.claude/HISTORY.md` rows.

## 6. Files touched (summary)

**New:** `harness/attribution.py`, `harness/retrieval/doc_categories.py`,
`harness/export/{__init__,registry,base,bundle,markdown,html}.py`,
`harness/configs/export/default.yaml`, `public/elements/CitationReview.jsx`,
`docs/CITATIONS.md`, tests (`test_attribution.py`, `test_doc_categories.py`,
`test_export.py`, + additions to retriever/adapter/postprocessor/obs tests).
**Modified:** `harness/schemas/answer.py`, `harness/prompts/agent_*.md` (4),
`harness/indexing/property_graph.py`, `harness/agents/workflow_adapter.py`,
`harness/retrieval/{postprocessors,config}.py`, `harness/obs/tracing.py` (+`__init__`),
`harness/export_traces.py`, `app.py`, `configs/retrieval/native.yaml` (comment), docs.

## 7. Verification

- **Offline suite** (all pure logic testable; baseline 448 passed / 2 skipped): span
  matching (exact/fuzzy/overlap/unmatched/zero-claims), classifier on real EMA URLs,
  exporter assertions (MD structure; HTML contains `<mark data-refs>` + embedded JSON + no
  external URLs), registry/config error paths, bundle building, retriever meta via fake
  store, adapter references join, reranker ordering, `log_citation_feedback` param mapping.
- **Headless boot** (this machine): chainlit boots; `/public/elements/CitationReview.jsx`
  served 200; export action callback path exercised with a stubbed bundle.
- **Runtime (GPU host)**: live turn → `[n]` markers clickable; Export → MD+HTML downloads,
  HTML highlight sync in a browser; CitationReview expands, verdict click lands as a
  `citation_*` MLflow assessment (visible in the trace Assessments panel); thread resume →
  review element still present with saved verdicts; recipe with `doc_type_priority`
  demotes an EPAR-first result.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM verbatim-claim discipline | Field descriptions + prompt rules; fuzzy matching; graceful fallback to today's behavior when claims absent/unmatched. |
| JSX whitelist limits the UI | Design uses only react + shadcn + lucide; highlight sync is plain React state; no external libs needed. |
| Retriever `_QUERY` change needs live Neo4j | Offline fake-store test now; GPU-host verify per RUNTIME_VERIFICATION conventions. |
| Feedback naming collisions in MLflow | Unique per-citation names (`citation_{rank}_{chunk8}`); `flush_trace_async_logging` before log (existing pattern). |
| Review volume outgrows 1–2 SMEs | Documented Label-Studio fallback consuming the export bundle; no rework of stages 1–3. |

## 9. Out of scope (explicit)

Learned re-ranking from feedback (needs data), whole-conversation export, multi-annotator
queues/IAA, extending the query cache with per-citation ratings, `page`-level PDF
provenance (never populated at ingest).
