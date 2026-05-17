# Exploration: PDF parsed cache → MongoDB linking

## Findings

### 1. Script was executed — 65,265 parsed_pdf.pkl files exist

Location: `~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap/<2-char>/<hash>/parsed_pdf.pkl`

Structure of each `PdfDocument`:
```
doc_id        str    — the original PDF URL (e.g. https://www.ema.europa.eu/...pdf)
markdown      str    — full extracted text as markdown (typically 2k–20k chars)
json          str    — raw JSON representation from pymupdf4llm
parsed_with   str    — "pymupdf4llm 0.2.9"
error         str    — empty string on success
doc           obj    — internal pymupdf document object (not serializable separately)
```

### 2. Cache URL lookup mechanism

`cache_utils.get_pdfs_from_cache()` walks the cache tree and reads each `meta` file
(plain-text Python dict with `url` key). This gives `(cache_path, url)` tuples — the
canonical URL-to-path mapping.

The cache hash is Scrapy's internal request fingerprint — not a simple URL hash.
So the only reliable way to go from URL → cache path is via the meta files.

### 3. MongoDB web_items structure

- Total documents: **115,101**
- PDF documents (`content_type: ["application/pdf"]`): **60,650**
- Schema: `{_id, url: [str], content_type: [str], file_links}`
- URL is stored as an **array** (even for single URLs)

### 4. Count mismatch

| Source | Count |
|--------|-------|
| parsed_pdf.pkl files in cache | 65,265 |
| PDF web_items in MongoDB | 60,650 |

The ~4,600 extra parsed files are PDFs that were scraped and cached but not inserted
into MongoDB (e.g., from a different spider run, or before the MongoDB pipeline was active).

---

## Integration options

### Option A: Add `parsed_pdf_path` field to web_items (local file link)

Add a `parsed_pdf_path: "/home/moritz/Nextcloud/.../parsed_pdf.pkl"` field to each
matching MongoDB document.

**Pros:**
- Minimal MongoDB footprint
- No data duplication
- Nextcloud syncs the pkl files cross-machine
- Easy to implement: iterate `get_pdfs_from_cache()`, match by URL, bulk update

**Cons:**
- Path is machine-specific (breaks if Nextcloud mount point changes)
- Must load pkl at runtime to access markdown
- No full-text search in MongoDB

**Best for:** lightweight pointer, when pkl files are always available locally.

---

### Option B: Embed markdown directly in web_items

Add `parsed_pdf_markdown: str` and `parsed_with: str` fields directly to each
web_items document.

**Pros:**
- Everything in MongoDB — no filesystem dependency
- Markdown is directly searchable/indexable (Atlas Search, regex)
- Works after Nextcloud sync to any machine

**Cons:**
- Large documents: avg ~10k chars × 60k docs ≈ ~600 MB additional storage
- Mixes raw scrape metadata with derived content
- Harder to re-run parsing (must update all documents)

**Best for:** when you want a single queryable source of truth.

---

### Option C: Separate `parsed_pdfs` collection (recommended)

Create a new collection `parsed_pdfs` keyed by URL:
```json
{
  "_id": "https://www.ema.europa.eu/.../foo.pdf",
  "markdown": "...",
  "parsed_with": "pymupdf4llm 0.2.9",
  "error": "",
  "cache_path": "~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap/ae/ae3551.../",
  "ingested_at": "2026-05-17T..."
}
```

Join at query time via `url` field (web_items URL array element).

**Pros:**
- Clean separation of concerns (raw scrape vs. derived content)
- URL as `_id` → O(1) lookup, no index needed
- Can rebuild from pkl without touching web_items
- Supports all 65,265 parsed files (including those not in web_items)
- TASK-007 corpus writer can do: `parsed_pdfs.find({error: ""})` to iterate all valid PDFs

**Cons:**
- Requires `$lookup` for joined queries (or application-level join)
- Two-step fetch vs. one document

**Best for:** this project — cleanest for the corpus extraction pipeline.

---

### Option D: Hybrid (path + markdown excerpt)

Store `cache_path` + first 500 chars of markdown in web_items for quick preview,
load full pkl on demand.

**Verdict:** Adds complexity without clear benefit over Option C.

---

## Recommendation

**Use Option C (separate `parsed_pdfs` collection)** for these reasons:

1. The corpus extraction pipeline (TASK-007) needs to iterate all valid parsed PDFs,
   not just those in web_items — a separate collection handles the 65,265 total naturally.
2. URL as `_id` gives O(1) lookup with no extra index.
3. Storing markdown in MongoDB makes TASK-007 (deduplication) straightforward: query
   the collection directly without filesystem access.
4. If parsing is rerun with a better parser, just drop and rebuild `parsed_pdfs`.

**Implementation sketch (linking script):**
```python
from ema_scraper.utils.cache_utils import get_pdfs_from_cache
import pickle
from pymongo import MongoClient, UpdateOne

client = MongoClient("localhost:27017")
col = client["ema_scraper"]["parsed_pdfs"]
col.create_index("_id")  # URL is _id, already unique

pdf_entries, _ = get_pdfs_from_cache()
ops = []
for cache_path, url in pdf_entries:
    pkl = cache_path / "parsed_pdf.pkl"
    if not pkl.exists():
        continue
    with open(pkl, "rb") as f:
        doc = pickle.load(f)
    ops.append(UpdateOne(
        {"_id": url},
        {"$set": {
            "markdown": doc.markdown,
            "parsed_with": doc.parsed_with,
            "error": doc.error,
            "cache_path": str(cache_path),
        }},
        upsert=True
    ))
    if len(ops) >= 500:
        col.bulk_write(ops)
        ops = []
if ops:
    col.bulk_write(ops)
```

This script processes all ~65,265 entries and upserts into `parsed_pdfs`.
Estimated runtime: ~5–10 min on local machine (disk-bound pkl reads).

## Next step

Run `/plan` or directly implement the linking script if you agree with Option C.
The script could live at `scripts/ingest_parsed_pdfs.py` in this repo.
