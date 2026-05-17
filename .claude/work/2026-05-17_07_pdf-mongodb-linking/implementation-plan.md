# Implementation Plan: Parsed PDF → MongoDB (Option C)

## Overview

Wire the 65,265 `parsed_pdf.pkl` files from the Scrapy cache into the corpus pipeline
by ingesting them into a dedicated `parsed_pdfs` MongoDB collection, then plumbing that
collection into the existing `build_corpus` pipeline via a MongoDB adaptor module.

This implements Option C from the exploration and completes TASK-007 from the main
implementation plan.

## Architecture

```
Scrapy cache (filesystem, Nextcloud-synced)
  ~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap/<2-char>/<hash>/
    ├── parsed_pdf.pkl    ← PdfDocument (markdown, doc_id, error, parsed_with)
    └── meta             ← plain-text dict with url key

        ↓  scripts/ingest_parsed_pdfs.py  (PDF-001)

MongoDB: ema_scraper.parsed_pdfs
  { _id: url, markdown, parsed_with, error, cache_path, ingested_at }

        ↓  corpus/sources/mongo_source.py  (PDF-003)

records_from_mongodb() → Iterator[QARecord]
  ├── HTML branch: web_items → html_extractor.extract_from_html()
  └── PDF branch:  parsed_pdfs → pdf_extractor.extract_from_markdown()

        ↓  corpus/build_corpus.py (already implemented, TASK-007A)

corpus/corpus.jsonl
```

## Key design decisions

- **URL as `_id`**: O(1) lookup, no extra index, natural dedup on re-ingest
- **Separate collection**: keeps `web_items` clean; collection is safe to drop/rebuild
- **Covers all 65,265 pkl files**: not just the 60,650 in `web_items`
- **`mongo_source.py` is pure adaptor glue**: no business logic, delegates to extractors
- **HTML body from web_items**: web_items stores `response_body`; `html_extractor` takes raw HTML string

## Task execution plan

### PDF-001 — `scripts/ingest_parsed_pdfs.py` (2h)

**File**: `scripts/ingest_parsed_pdfs.py`

```python
# Key interface:
# python scripts/ingest_parsed_pdfs.py [--dry-run] [--limit N]
```

Implementation notes:
- Add `ema_scraper` to `sys.path` at the top (or use `importlib`) to access
  `cache_utils.get_pdfs_from_cache()` without installing the scraper package
- Batch size 500 for `bulk_write` (balance memory vs round-trips)
- `UpdateOne({"_id": url}, {"$set": {...}}, upsert=True)` — idempotent
- `ingested_at` = `datetime.utcnow().isoformat()`
- Skip entries where `parsed_pdf.pkl` does not exist (safety check)
- Print final: `Ingested: N  Errors: E  Skipped: S  Total: T`

### PDF-002 — Validate ingestion (1h)

Run the script, verify in mongosh:
```js
db.parsed_pdfs.countDocuments()            // expect 60k–65k
db.parsed_pdfs.findOne({error: {$ne: ""}}) // sample error doc
db.parsed_pdfs.aggregate([{$sample:{size:5}}, {$project:{_id:1, parsed_with:1, markdownLen:{$strLenCP:"$markdown"}}}])
db.stats()                                 // collection size
```

Document findings in exploration.md.

### PDF-003 — `corpus/sources/mongo_source.py` (2h)

**Files**: `corpus/sources/__init__.py`, `corpus/sources/mongo_source.py`

```python
def records_from_mongodb(
    host: str = "localhost:27017",
    db: str = "ema_scraper",
    html_query: dict | None = None,
    pdf_query: dict | None = None,
) -> Iterator[QARecord]:
```

HTML branch:
- Query: `web_items.find(html_query or {"content_type": "text/html"}, {"url": 1, "response_body": 1})`
- Call: `html_extractor.extract_from_html(body, url[0])`

PDF branch:
- Query: `parsed_pdfs.find(pdf_query or {"error": ""}, {"_id": 1, "markdown": 1})`
- Call: `pdf_extractor.extract_from_markdown(doc["markdown"], doc["_id"])`

Note: check what `web_items` HTML documents look like (content_type field, response_body availability).

### PDF-004 — Integration test + corpus run (2h)

**File**: `tests/test_mongo_source.py`

```python
@pytest.mark.integration
def test_records_from_mongodb_yields_qa_records():
    records = list(itertools.islice(records_from_mongodb(pdf_query={"error": ""}), 20))
    assert len(records) >= 1
    assert all(isinstance(r, QARecord) for r in records)
```

Then run full corpus build:
```bash
python -c "
from corpus.sources.mongo_source import records_from_mongodb
from corpus.build_corpus import build_corpus
from pathlib import Path
stats = build_corpus(records_from_mongodb(), Path('corpus/corpus.jsonl'))
print(stats)
"
```

## Quality gates

- `ruff check . && mypy .` must pass after each task
- No `pymongo` import in `build_corpus.py` (existing constraint)
- Integration tests marked `pytest.mark.integration` (skip in CI without live DB)

## Files to create / modify

| File | Action |
|------|--------|
| `scripts/ingest_parsed_pdfs.py` | Create |
| `corpus/sources/__init__.py` | Create |
| `corpus/sources/mongo_source.py` | Create |
| `tests/test_mongo_source.py` | Create |
| `.claude/HISTORY.md` | Append row |
| `exploration.md` (this work unit) | Update with validation results |
