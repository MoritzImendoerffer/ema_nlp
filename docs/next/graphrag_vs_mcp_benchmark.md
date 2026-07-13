# Plan: GraphRAG × MCP — a comparison-and-complementarity benchmark

*Status: 💡 designed (2026-07-12) — **build gated per §8**, per the "complexity must be
justified by a benchmark failure" rule. This is a **research/eval program**, not a single
feature: it defines four system arms, two benchmark slices, and a metric frontier. Each arm
is built only after the prior phase produces the specific measurable gap that justifies it.*

> **Reviewer note.** This is a design for review. Nothing here is implemented yet. It answers
> four questions raised in discussion (2026-07-12) and turns them into an executable program:
> 1. Can the openpharma MCP servers **create and benchmark** our extracted ontology?
> 2. Does comparing **ontology-GraphRAG (Cypher + vector RAG)** to the **MCP-tool** approach
>    make sense?
> 3. Can the MCP servers / BioClaw **generate benchmark items** for our RAG?
> 4. The two approaches **complement** each other — the plan must measure that, not just race them.

---

## 1. Why

We have a deep, unstructured **RAG-over-EMA-corpus** system (hierarchical `PropertyGraphIndex`
on Neo4j, 79,882 docs / 5.82M leaf embeddings, span-level attribution, a 45-item T1–T4
benchmark with a lift metric). The [openpharma](https://github.com/openpharma-org) MCP servers
(and the [BioClaw](https://github.com/uh-joan/bioclaw) bundle of 41 of them) are the *opposite*
shape: broad, structured, live, authoritative APIs with **no** corpus retrieval, **no** graph
reasoning, **no** provenance beyond "the API said so."

The strategic question is not "which is better" — that is a category error, because they are good
at different question types. The question is **where each wins, where they cross over, and
whether a hybrid beats either alone**. Answering it produces three things we want anyway:

- a **capability frontier** (arm × question-type × metric) that tells us *which technique to
  route which question to* — directly feeding the recipe engine and the ablation plan
  (`project_roadmap/ABLATIONS.md`);
- an **external oracle** for measuring the quality of the (currently deferred) Layer-2 ontology
  extraction — we cannot hand-label typed triples at scale, but an API can check a subset;
- a **benchmark generator** for the factual slice, scaling us past 45 hand-curated items.

The honest driver: on pure factual lookup an API will beat us, cheaper. The defensible ground is
T3/T4 reasoning-over-narrative *with* provenance. This program is how we **prove** that boundary
with numbers instead of asserting it, and how we turn the MCP servers from a competitor into a
component (Arm D) and a measurement instrument (§5, §6).

---

## 2. What already exists (build on, don't rebuild)

| Capability | Where | Reuse in this plan |
|---|---|---|
| Config-driven recipe engine (tools + profile + judge, zero engine changes to add an arm) | `harness/configs/recipes/*.yaml`, `build_recipe` → `AgentWorkflowAdapter` | Each **arm = one recipe** (§4) |
| Tool registry by name | `harness/tools/registry.py` (`@register_tool`, `build_tools`) | New tools `ema_info`, `ontology_query` register here (§7) |
| Vector+graph retriever with steering | `harness/retrieval/` (`ema_search`, `neo4j_hier`/`neo4j_steered`) | **Arm A** as-is |
| Parametrized-Cypher retriever | `harness/retrieval/native_pg.py::build_cypher_template_retriever` (`CypherTemplateRetriever`) | Backs **`ontology_query`** — GraphRAG's structured arm (§7.2) |
| Typed ontology schema + extractor mapping | `harness/ontology/` (`schema.py`, `enrich.py`, `configs/ontology/ema.yaml`) | **Layer-2 extraction** for Arm B; `enrich.py --scope nitrosamines` is a ready bounded pilot |
| Per-type MLflow eval with genai judges | `scripts/run_eval.py` → `harness/eval/runner.py` (`to_eval_data`, `ema_judges`, one run per type) | Extended with new arms, slices, scorers (§6) |
| Claim-level structured answers + span attribution | `harness/schemas/answer.py` (`RegulatoryAnswer`, `Claim`), `harness/attribution.py` | Provenance-granularity metric (§6) |
| Benchmark (45 items, T1×20/T2×10/T3×10/T4×5) | `benchmark/benchmark.jsonl` | **Slice P** (§5) |

**Not yet present (this plan adds):** an MCP client tool + record/replay cache; a run of the
(deferred) ontology extractor; an `ontology_query` tool; three recipes; an MCP-generated
benchmark slice; three new scorers; the ontology-vs-oracle sub-study. One dependency gap:
`pyproject.toml` pins only `llama-index-core>=0.12` — the MCP tool needs
`llama-index-tools-mcp` added (or a ~40-line hand-rolled client; §8-D).

---

## 3. The central honest constraint: our benchmark and the MCP serve *different* facts

This shapes the whole design, so it comes first.

Our existing 45 items are about regulatory **process/procedure** — e.g. *"How far in advance must
an MAH inform the Agency before a worksharing variation?"* (gold: "at least 2 months"), *"CHMP
opinion timeline for an Article 30 referral?"* (gold: "60 days, extendable to 150"). These live in
**guideline/Q&A prose**.

The openpharma EMA MCP (`ema_info`, 14 methods) serves **product/safety records**: approvals,
orphan designations, supply shortages, referrals, DHPCs, PSUSAs, PIPs. It does **not** expose
procedural deadlines from guideline text.

**Consequence:** the MCP arm will *near-zero* on Slice P's T1 items — not because it is bad, but
because those facts are outside its coverage. That is a **designed finding**, not a bug. To make
the comparison fair *and* interesting we need a second benchmark slice that lives on the MCP's
home turf (Slice S, §5.2), where the extracted ontology can compete with the API head-to-head.
Reporting only Slice P would slander the MCP; reporting only Slice S would slander the RAG. Both
slices, always split by type — never aggregated.

---

## 4. Design — four arms

Each arm is a recipe; the engine is unchanged. Arms A–C isolate a single technique so the frontier
is attributable; Arm D is the complementarity thesis.

| Arm | Name | Tools | Index profile | What it isolates |
|---|---|---|---|---|
| **A** | Vector RAG *(baseline, exists)* | `ema_search`, `resolve_substance` | `neo4j_hier` | Semantic retrieval over narrative |
| **B** | GraphRAG | `ema_search`, `ontology_query`, `resolve_substance` | `neo4j_graph` *(Layer-2 extracted)* | Ontology + parametrized Cypher **on our own graph** |
| **C** | MCP | `ema_info` (+ `resolve_substance`) | *(retrieval: none)* | Structured live API — the "BioClaw" shape |
| **D** | Hybrid | `ema_search`, `ontology_query`, `ema_info`, `resolve_substance` | `neo4j_graph` | Agent routes across all three — **the thesis** |

**The thesis (Arm D):** on a *mixed* benchmark spanning both slices and all four types, Hybrid
≥ max(A, B, C) on correctness, **and** Hybrid shows the **lowest variance across question types**
(robustness) — because it can send each question to the tool that owns it. A single arm is forced
to answer questions outside its home turf; the hybrid is not. Variance-reduction is the measurable
signature of complementarity, and it is what neither BioClaw nor a pure-RAG system can show.

---

## 5. Design — two benchmark slices

### 5.1 Slice P — Process / narrative *(exists: `benchmark/benchmark.jsonl`)*
The current 45 items. Home turf: A/B. Purpose: show the RAG stack's reasoning depth and map the
MCP's coverage boundary (expected: C fails T1, is absent on T3/T4).

### 5.2 Slice S — Structured / product-safety *(new: `benchmark/benchmark_mcp.jsonl`)*
Auto-generated from `ema_info` (§7.4). Home turf: C. The **head-to-head** slice where GraphRAG's
extracted ontology competes with the API on the same facts. Composition (~30 items to start):

- **T1** (lookup): *"What is the EMA product number / approval status of `<product>`?"* — gold from
  `get_medicine_by_name`.
- **T2** (enumeration): *"Which orphan-designated medicines target `<condition>`?"* — gold =
  the **complete set** from `get_orphan_designations`. This is where vector RAG structurally
  cannot compete (it ranks, it does not enumerate) and Cypher-on-ontology can.
- **T3** (multi-hop): *"Is any product containing `<substance>` under an active supply shortage,
  and what does the relevant guideline say about managing shortages?"* — `get_supply_shortages`
  (structured) **+** narrative guideline. Neither pure arm answers it alone; Hybrid should.
- **T4** stays sparse here — synthesis is Slice P's job.

**Circularity guard (answers Q3's trap):** items generated *from* `ema_info` are used to grade the
**RAG-side arms (A, B)** and the **Hybrid (D)**. Grading the **MCP arm (C)** against MCP-derived
gold is self-grading → for C on Slice S, treat its score as a **reference upper bound**, not a
competitor cell, *or* oracle it against a **held-out snapshot** taken at a different `as_of`
(§7.5). This is stated on every Slice-S result table.

**Contamination:** product/approval facts are likely memorized by the model → high closed-book →
low lift on Slice S T1. Fine — we report **lift per type** (headline metric) and read a low-lift
T1 cell as "measures plumbing, not reasoning," never as system quality.

---

## 6. Design — the metric frontier (the deliverable)

Every arm is scored per **(slice × type)** on:

| Metric | Source | Notes |
|---|---|---|
| **Correctness** | existing genai correctness judge vs `gold_answer` | already wired in `ema_judges` |
| **Faithfulness / groundedness** | existing faithfulness judge vs `context_passages` | **adapt** for Arm C: its "context" is structured JSON records, not passages (§8-E) |
| **Completeness** | **new** scorer | for T2 enumeration: recall of the API-derived complete set |
| **Freshness** | **new** scorer | only on items whose gold has a temporal component; measures whether the answer reflects current state. MCP wins by construction; quantifies the staleness cost of the frozen corpus |
| **Provenance granularity** | **new** scorer | span (RAG) vs graph-path (GraphRAG) vs record-id (MCP) — can a `Claim` be traced to a citable unit? |
| **Cost / latency** | run instrumentation | output tokens, tool-call count, wall-clock — the operational axis |
| **Lift** | open − closed book, per type | **headline**; reuses `docs/next/closed_book_lift.md` machinery |

**Output = a frontier matrix**, not a winner. Hypothesised shape (to be *tested*, not assumed):

| Question class | Vector RAG (A) | GraphRAG (B) | MCP (C) | Hybrid (D) |
|---|---|---|---|---|
| Slice P · T1 (process lookup) | ✅ strong | ✅ strong | ❌ ~0 *(coverage boundary)* | ✅ strong |
| Slice P · T3/T4 (synthesis) | ✅ strong | ✅ strong+ | ❌ ~0 *(no narrative)* | ✅ strong |
| Slice S · T1 (product lookup) | ⚠️ fact-fragile | ✅ strong | ✅✅ authoritative | ✅✅ |
| Slice S · T2 (enumeration) | ❌ cannot enumerate | ✅ Cypher-complete | ✅✅ API-complete | ✅✅ |
| Slice S · T3 (shortage + guideline) | ⚠️ partial | ⚠️ partial | ⚠️ facts only | ✅✅ **only D** |
| Freshness (any live fact) | ❌ frozen | ❌ frozen | ✅✅ live | ✅✅ (via `ema_info`) |
| Variance across types | mid | mid | **high** | **lowest ← thesis** |

The two cells that make or break the story: **Slice S · T3** (does only Hybrid clear it?) and
**Variance** (is Hybrid measurably the most robust?).

---

## 7. Architecture — how it plugs into the codebase

Nothing structural changes; every piece is a registry entry, a config, or a script.

### 7.1 MCP tool — `harness/tools/mcp_tools.py`
```python
@register_tool("ema_info")
def build_ema_info_tool(*, mcp_config=None, **_):
    from llama_index.tools.mcp import BasicMCPClient, McpToolSpec   # new dependency (§8-D)
    from harness.eval.mcp_cache import cached_mcp_client            # record/replay wrapper
    client = cached_mcp_client(BasicMCPClient(mcp_config["endpoint"]), mcp_config)
    return McpToolSpec(client, allowed_tools=mcp_config["methods"]).to_tool_list()
```
Config `harness/configs/mcp/ema.yaml`: `endpoint`, `methods: [get_medicine_by_name,
get_orphan_designations, get_supply_shortages, ...]`, `cache: replay`.

### 7.2 GraphRAG tool — `harness/tools/ontology_query.py`
Wraps the **existing** `build_cypher_template_retriever`. A small library of parametrized Cypher
templates keyed to the `ema.yaml` `validation_schema` triples; the LLM fills only the parameters
(safer than free TextToCypher). Example template for `Substance —SUBJECT_TO→ Procedure`:
```cypher
// template: substance_procedures
MATCH (s:Substance)-[:SUBJECT_TO]->(p:Procedure)
WHERE toLower(s.name) CONTAINS toLower($substance)
RETURN p.name AS procedure, p.reference AS ref LIMIT 25
```
```python
@register_tool("ontology_query")
def build_ontology_query_tool(*, index=None, cypher_templates=None, **_):
    from harness.retrieval.native_pg import build_cypher_template_retriever
    # exposes a FunctionTool that picks a template by intent, fills params, runs it
```

### 7.3 Recipes — `harness/configs/recipes/{graph_agent,mcp_agent,hybrid_agent}.yaml`
```yaml
# hybrid_agent.yaml — the thesis arm
recipe:
  label: "Hybrid agent (RAG + GraphRAG + MCP)"
  orchestration:
    system_prompt: agent_hybrid.md   # routing guidance: facts/enumeration→ema_info/ontology_query,
    tools: [ema_search, ontology_query, ema_info, resolve_substance]  # rationale→ema_search
    output_schema: RegulatoryAnswer
  retrieval: { index_profile: neo4j_graph, pipeline: none }
  generation: { model: claude_opus, temperature: 0.0 }
  judge: { enabled: false }
```
`mcp_agent.yaml` sets `tools: [ema_info]` and `retrieval.index_profile: none`.

### 7.4 Benchmark generator — `scripts/gen_mcp_benchmark.py`
`ema_info` records → templated Q/A → `benchmark/benchmark_mcp.jsonl`, each item carrying
`gold_source: {mcp_method, args, as_of}` provenance and a `slice: S` tag. Templates per type as in
§5.2. Human spot-review before an item is admitted (auto-gen sets the floor, not the ceiling).

### 7.5 Reproducibility harness — `harness/eval/mcp_cache.py`
VCR-style record/replay keyed on `(server, method, sha1(sorted args))`; cassettes under
`harness/eval/fixtures/mcp/`. `EMA_MCP_CACHE=record` hits live + stamps `as_of`; `replay` is
deterministic and offline. **This is what makes the whole comparison reproducible** and immune to
API downtime — it neutralises the single biggest MCP drawback for eval use.

### 7.6 Ontology extraction — reuse `harness/ontology/enrich.py`
`python -m harness.ontology.enrich --schema ema --scope nitrosamines` (bounded pilot; the
nitrosamine scope also exercises the "AI = Acceptable Intake" disambiguation) writes typed
entities/relations into the graph → the `neo4j_graph` profile Arm B reads. Full `--scope all` is
deferred (cost + GPU-crash risk, see memory `gpu_gsp_crash_under_sustained_load`).

### 7.7 Ontology-vs-oracle sub-study — `scripts/eval_ontology.py` *(answers Q1)*
For each extracted triple whose relation is **API-coverable** (e.g. a `Substance`/`Product`
resolvable in `ema_info`), verify against the API. Metrics: **triple precision on API-covered
relations**, **entity-resolution accuracy** (extracted node ↔ canonical MCP record). Relations the
API cannot cover (`SETS_LIMIT`, `JUSTIFIED_BY`, `SUPERSEDES`, `MANDATED_BY`) get **human
spot-check**, not an API oracle. Recall is explicitly **coverage-on-overlap** (the API undercounts
because our corpus legitimately has relations it never modelled) — reported as such, never as
"ontology recall."

### 7.8 Eval runner extensions — `harness/eval/`, `scripts/run_eval.py`
New scorers (completeness, freshness, provenance) added to `ema_judges`; `run_recipe_benchmark`
learns `--slice {P,S,all}` and `--arm`; results still land as one MLflow run per type, now tagged
`ema.arm` / `ema.slice`.

---

## 8. Implementation phases (gated — each earns the next)

Ordered so the cheapest, most decision-useful work comes first and each arm is justified by a
measured gap, per the repo's complexity rule.

- **Phase 0 — MCP tool + cache + smoke.** `mcp_tools.py`, `mcp_cache.py`, `configs/mcp/ema.yaml`,
  dep added. *Gate:* none (foundational, cheap). *Done when:* a test replays a cassette and
  `ema_info` returns a record offline.
- **Phase 1 — Slice S generator.** `gen_mcp_benchmark.py` → ~30 reviewed items in
  `benchmark_mcp.jsonl`. *Answers Q3.* *Done when:* items validate against the benchmark schema and
  carry MCP provenance + `as_of`.
- **Phase 2 — Baseline map (Arm A on both slices).** No new arm — run the *existing* Vector-RAG
  recipe on P and S. **This is the gating checkpoint:** it produces the concrete failures
  (S·T2 enumeration miss? S·T1 fact-fragility? P coverage of C?) that justify building B and C.
  If A already handles S, we stop and write that up. *Done when:* the frontier's Arm-A column is
  filled and the specific gaps are named.
- **Phase 3 — MCP arm (C).** Cheap (Phase-0 tool + a 2-tool recipe). Run on both slices. *Done
  when:* the coverage-boundary finding (C ≈ 0 on Slice P) is quantified and the A-vs-C frontier v1
  exists.
- **Phase 4 — Ontology + GraphRAG arm (B).** *Gate:* Phase 2 showed an enumeration/precision gap a
  graph would fix. Run `enrich.py --scope nitrosamines`; build `ontology_query` + `graph_agent`;
  run the **ontology-vs-oracle sub-study** (§7.7, *answers Q1*). *Done when:* Arm-B column filled +
  a triple-precision-on-overlap number exists.
- **Phase 5 — Hybrid (D) + full frontier + lift.** Build `hybrid_agent`; run all arms × both slices
  × lift. *Answers Q2 and Q4.* *Done when:* the frontier matrix is complete and the two make-or-break
  cells (S·T3, variance) are decided.
- **Phase 6 — Write-up.** The frontier + the complementarity result → `docs/` + `.claude/HISTORY.md`.

Phases 0–3 are low-risk and independently valuable (we get an MCP tool + a bigger benchmark even if
we never build GraphRAG). Phase 4 is the expensive one and is explicitly gated.

---

## 9. A worked example (one item, all four arms)

**Question (Slice S · T3):** *"Is any product containing valsartan currently under a supply
shortage in the EU, and what does EMA guidance say about managing nitrosamine-related shortages?"*

| Arm | Trajectory | Expected outcome |
|---|---|---|
| **A** Vector RAG | `ema_search("valsartan shortage nitrosamine guidance")` | Retrieves guidance prose; **guesses** shortage status from possibly-stale text → fact-fragile, maybe wrong on "currently" |
| **B** GraphRAG | `ontology_query(substance="valsartan")` graph hop + `ema_search` for guidance | Structured hop + narrative; still **stale** on live shortage (graph is frozen) |
| **C** MCP | `ema_info(get_supply_shortages, substance="valsartan")` | **Authoritative + live** shortage list; **cannot** produce the guidance rationale → half the answer |
| **D** Hybrid | `ema_info` for live status **+** `ema_search` for guidance, one `RegulatoryAnswer` with both claims cited | **Complete**: live fact (record-cited) + rationale (span-cited). *The cell only D clears.* |

This single item is the whole thesis in miniature: A/B are stale on the fact, C is empty on the
rationale, D composes both — and the frontier is the statistical version of this table.

---

## 10. Open decisions (for reviewer)

- **D-A · MCP transport & trust.** Hosted openpharma endpoint vs. stdio-spawn the server in a
  container (à la BioClaw)? These are *unofficial* wrappers — pin a version, and decide whether we
  trust `ema_info` as an oracle at all, or only as a convenience arm. *(Recommend: stdio-spawn a
  pinned image; oracle only via the record/replay snapshot.)*
- **D-B · Ontology scope.** `nitrosamines` pilot only, or a second scope? Full `--scope all` is out
  for v1 (cost + GPU risk). The frontier's Arm-B cells are only valid for the extracted scope —
  Slice S items must be drawn from within it.
- **D-C · Slice-S circularity.** For Arm C on Slice S: reference-upper-bound, held-out-snapshot
  oracle, or human? *(Recommend: reference upper bound + a small human-checked subset.)*
- **D-D · Dependency.** Add `llama-index-tools-mcp`, or hand-roll a ~40-line MCP client to avoid
  the dep? *(Recommend: add the library; it is the standard path and LlamaIndex-native.)*
- **D-E · Structured-context faithfulness.** The faithfulness judge expects text passages; Arm C's
  evidence is JSON records. Adapt the judge, or exempt C from faithfulness and report groundedness
  differently? *(Recommend: render records to a canonical text block for the judge; note the
  asymmetry.)*
- **D-F · Freshness measurement.** Needs items whose gold changed *after* the corpus snapshot.
  Source them from `get_supply_shortages` "Resolved" transitions? Decide before Phase 1.

---

## 11. Success criteria

1. A **frontier matrix** (arm × slice × type × metric) in MLflow, decision-useful enough to set
   recipe routing policy.
2. A demonstrated **complementarity result**: Hybrid ≥ max(A,B,C) on the mixed benchmark **and**
   lowest cross-type variance — or a documented refutation.
3. An **ontology precision-on-overlap** number from the API oracle (Q1), with the coverage caveat
   stated.
4. Every eval run **reproducible offline** from cassettes (no live API in the scored path).
5. The **coverage-boundary finding** (MCP ≈ 0 on Slice P) quantified and framed as a capability
   map, not a defect.

---

## 12. What this explicitly is NOT (v1 scope locks)

- Not full-corpus ontology extraction (bounded scope only).
- Not FDA/genomics/other openpharma servers — EMA `ema_info` only (same domain keeps the
  comparison clean; other servers are a later frontier).
- Not a live-API dependency in the scored eval path (cassettes only).
- Not a replacement for the hand-curated benchmark — MCP generation *augments* Slice S; the T3/T4
  reasoning items stay human-authored.
- Not model training — consistent with `DECISIONS.md` (runtime few-shot only in the live path).
