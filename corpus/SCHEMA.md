# Corpus Q&A Record Schema

Every record in `corpus.jsonl` conforms to this schema. One JSON object per line, UTF-8 encoded.

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `qa_id` | `string` | ✅ | Stable identifier: `sha256(source_url + "\x00" + normalised_question)[:16]` |
| `question` | `string` | ✅ | Full question text, preserving original phrasing |
| `answer` | `string` | ✅ | Full answer text (may include nested structure as plain text) |
| `source_url` | `string` | ✅ | Canonical URL of the source page or PDF |
| `source_type` | `string` | ✅ | `"html_accordion"` or `"pdf"` |
| `source_title` | `string` | ✅ | Document title, e.g. `"Nitrosamines Q&A"` |
| `reference_number` | `string` | ✗ | EMA reference number, e.g. `"EMA/409815/2020 Rev.23"` (PDF only) |
| `topic_path` | `string` | ✅ | URL-derived breadcrumb, e.g. `"/human-regulatory/post-authorisation/variations"` |
| `revision` | `string` | ✗ | Revision string from revision history table, e.g. `"Rev.23"` |
| `last_updated` | `string` | ✗ | ISO 8601 date string, e.g. `"2023-10"` (month precision acceptable) |
| `cross_refs` | `list[string]` | ✅ | `qa_id`s of explicitly cross-referenced Q&As (`"see Q&A N"` patterns). Empty list if none. |
| `extraction_confidence` | `string` | ✅ | `"high"`, `"medium"`, or `"low"` (see below) |

## Confidence levels

| Value | When assigned |
|-------|---------------|
| `"high"` | Numbered heading question, clean Q/A split, or accordion heading is a grammatical question |
| `"medium"` | Accordion heading is a statement not a question; or PDF regex matched but boundary is approximate |
| `"low"` | Heuristic split; content may bleed across Q&A boundaries; manually review before benchmark use |

## Example record

```json
{
  "qa_id": "a3f7c2d1e9b04512",
  "question": "Should the risk assessment for nitrosamines be submitted with the marketing authorisation application?",
  "answer": "Yes. Applicants should submit a nitrosamine risk assessment as part of their dossier...",
  "source_url": "https://www.ema.europa.eu/en/documents/scientific-guideline/questions-and-answers-nitrosamines_en.pdf",
  "source_type": "pdf",
  "source_title": "Questions and answers on nitrosamines in medicinal products for human use",
  "reference_number": "EMA/409815/2020 Rev.23",
  "topic_path": "/documents/scientific-guideline",
  "revision": "Rev.23",
  "last_updated": "2023-10",
  "cross_refs": ["b9d1e4f2a7c03821", "c2a8f5d3b1e04719"],
  "extraction_confidence": "high"
}
```

## Deduplication rule

When the same Q&A appears in both an HTML accordion and a PDF, the **PDF record is kept** (it carries revision metadata). The HTML record is dropped and logged in `corpus/dedup_log.jsonl`.

## Null / missing values

- `string` fields that are not available: omit the key or set to `""` (empty string)
- `cross_refs`: always present as a list (use `[]` when empty, never `null`)
- `extraction_confidence`: always present; no nulls allowed
