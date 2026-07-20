# Benchmark Item Schema

Every record in `benchmark.jsonl` conforms to this schema. One JSON object per line, UTF-8 encoded.

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `bench_id` | `string` | ✅ | Stable identifier: `T<type>-<zero-padded-seq>`, e.g. `"T1-001"` |
| `question` | `string` | ✅ | The canonical question text |
| `paraphrases` | `list[string]` | ✅ | 1–3 rephrasings of the question (different surface form, same information need) |
| `type` | `string` | ✅ | `"T1"`, `"T2"`, `"T3"`, or `"T4"` (see taxonomy below) |
| `gold_answer` | `string` | ✅ | Canonical answer text, SME-verified |
| `gold_qa_ids` | `list[string]` | ✅ | `qa_id`s from `corpus.jsonl` that must be retrieved to answer correctly |
| `gold_sources` | `list[object]` | ✅ | Source references: `{"url": "...", "page": null}` for HTML, `{"url": "...", "page": 12}` for PDF |
| `topic_path` | `string` | ✅ | Topic cluster of the primary source Q&A |
| `zero_shot_known` | `object` | ✗ | Map of `model_id → bool`: whether model answered correctly closed-book. Populated by TASK-015. |
| `notes` | `string` | ✗ | Curation note: why this item has its type label, any ambiguity, related items |

## Question type taxonomy

| Type | What it tests | Gold requires |
|------|--------------|---------------|
| `T1` Lookup | Single-Q answer from one source | 1 `qa_id` |
| `T2` Scoping | Correct selection among topically-adjacent Q&As | 1 correct + explicit distractors noted |
| `T3` Multi-hop | Traversal of `cross_refs` chain (≥2 hops) | ≥2 `qa_id`s in chain order |
| `T4` Synthesis | Combination of ≥2 Q&As from different source docs | ≥2 `qa_id`s from distinct `source_url`s |
| `T5` Link-traversal showcase | Following document links from a hub page | anchor + link targets in `gold_sources` (separate file — see below) |

## Example record

```json
{
  "bench_id": "T1-001",
  "question": "What is the acceptable intake (AI) for NDMA in medicines for chronic use?",
  "paraphrases": [
    "What is the acceptable daily limit for NDMA in long-term medications?",
    "What limit applies to N-nitrosodimethylamine in chronically-used medicinal products?"
  ],
  "type": "T1",
  "gold_answer": "The acceptable intake for NDMA in medicines intended for chronic use is 26.5 ng/day.",
  "gold_qa_ids": ["a3f7c2d1e9b04512"],
  "gold_sources": [
    {"url": "https://www.ema.europa.eu/en/documents/scientific-guideline/questions-and-answers-nitrosamines_en.pdf", "page": 4}
  ],
  "topic_path": "/documents/scientific-guideline",
  "zero_shot_known": {},
  "notes": "T1: single-source lookup. Uses specific numeric threshold — more resistant to memorization than conceptual questions."
}
```

## Stratification targets (v1)

| Type | Target count |
|------|-------------|
| T1 Lookup | 20 |
| T2 Scoping | 10 |
| T3 Multi-hop | 10 |
| T4 Synthesis | ≥5 |
| **Total** | **≥45** |

## Contamination resistance guidance

Prefer questions whose gold answers depend on:
- Specific numeric thresholds (e.g. `26.5 ng/day`, `100 ng/day`)
- Procedural timelines or deadlines
- Cross-reference traversal (inherently multi-step, harder to memorize)
- T4 composite/counterfactual items you authored (not in any single source document)

At least 5 items should be `T4` composite or post-cutoff — these are contamination-resistant by construction.

## T5 — link-traversal showcase (`benchmark/showcase.jsonl`)

A **separate file**, not part of the 45-item curated benchmark: five items whose
purpose is to exercise and *show* tree-aware retrieval (vector hit → `LINKS_TO`
expansion → site-tree ancestor context), not to measure benchmark accuracy.

- Same record schema, `type: "T5"`, `bench_id: T5-00n`.
- **Anchors are hubs, chosen generically** by link fan-out, not by topic. The
  selection query (run against the live graph; the resulting URLs — never a
  category name — go into the JSONL):

  ```cypher
  MATCH (d:Document {category:'medicine_page'})-[:LINKS_TO]->(t:Document)
  WITH d, count(t) AS fan ORDER BY fan DESC LIMIT 10
  RETURN d.source_url, d.title, fan
  ```

- `gold_qa_ids` is `[]` — **a deliberate deviation**: these items are not mined
  from `corpus.jsonl` Q&A pairs. `gold_sources` names the anchor page plus
  representative link targets.
- `gold_answer` is a key-fact summary (documents that exist + timeline
  milestones) so the correctness judge can grade containment. **Judges are
  secondary here**; the primary artifact is the rendered chain HTML
  (`scripts/render_trace.py --run-id …`), which shows the traversal.

Run it with the tree recipe:

```bash
python scripts/run_eval.py --recipe tree_agent --benchmark benchmark/showcase.jsonl --types T5
python scripts/render_trace.py --run-id <mlflow_run_id>   # chains → $EMA_RESULTS_DIR/chains
```

**Do not run `validate_benchmark.py` against `showcase.jsonl`** — it hardcodes
the T1–T4 vocabulary and the v1 stratification counts and will reject the file
by design.
