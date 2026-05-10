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
