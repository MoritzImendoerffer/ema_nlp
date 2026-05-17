# Exploration: Retrieval Coverage Gap

**Triggered by:** "process characterization" query returned zero relevant results in the chat UI.

---

## Root causes (three compounding issues)

### Issue 1 — Chat UI defaults to mini_corpus.jsonl (CRITICAL)

`app.py:32` and `harness/embed.py:34` both set:
```python
DEFAULT_CORPUS = REPO_ROOT / "corpus" / "mini_corpus.jsonl"
```

`mini_corpus.jsonl` has **156 records** (only `human-regulatory-overview` topic).  
`corpus.jsonl` has **26,251 records**.

The chat UI is effectively blind to 99.4% of the corpus.

The env var override `EMA_CORPUS_PATH` exists in `app.py` (line 11 comment, line 74), but:
- It's not documented anywhere
- The default is mini_corpus, so it only helps if you already know to set it
- `harness/embed.py` uses its own `DEFAULT_CORPUS` constant — they can diverge

### Issue 2 — 2,797 accordion HTML pages not extracted to corpus

MongoDB `web_items` collection:
- **22,743** total HTML pages
- **6,095** pages have `accordion-item` class (the structure the extractor handles)
- **Only 3,298** unique source URLs appear in `corpus/corpus.jsonl`
- **~2,797 accordion pages are in MongoDB but not in the corpus**

Key missed Q&A pages:
| URL | Relevance |
|-----|-----------|
| `ich-q8-q9-q10-questions-answers-scientific-guideline` | ICH Q8 = Pharmaceutical Development / QbD — directly covers process characterization |
| `questions-answers-post-approval-change-management-protocols` | Post-approval process changes |
| `quality-working-party-questions-answers-api-mix` | CMC/API quality |
| `questions-answers-gene-therapy-scientific-guideline` | Gene therapy quality |
| `ich-m4-common-technical-document-*-questions-answers` | CTD format Q&A |
| `ich-s3a-toxicokinetics-*-questions-answers` | Toxicokinetics Q&A |

### Issue 3 — ema-inpage-item structure not supported

**15,488 HTML pages** in MongoDB use the `ema-inpage-item` structure (not Bootstrap accordion). These pages organize content as sections (`<div id="ema-inpage-item-XXXXX">`) with `rounded-title` h2 headings. The ICH Q8/Q9/Q10 page is an example: it has 7 `ema-inpage-item` sections but **zero `accordion-item` elements** — the extractor produces nothing for it.

However, examination of the ICH Q8 page shows it's a **document index page** (intro text + links to PDFs), not a Q&A page. The actual Q&A content for ICH Q8 may be in the linked PDFs (which should be in `parsed_pdfs`).

---

## "Process characterization" in current corpus

Full corpus search results:
| Source | Topic | Content |
|--------|-------|---------|
| `html_accordion` | `/human-regulatory-overview/research-and-development/scientific-guidelines` | Chromatography resin Q&A — mentions "process characterisation data" in passing |
| 8× `pdf` | various | Section headers / TOC entries, not real answers |

**MongoDB HTML search**: Only 2 pages mention "process charact" in html_raw:
1. Biological medicinal products Q&A (`questions-answers-biological-medicinal-products`) — IS in corpus (32 records)
2. Process validation guideline — IS in corpus as PDF

The term "process characterization" is used in regulatory PDFs (validation guidelines, ICH Q8 PDF) which ARE being parsed. The parsed_pdfs collection has 38,948 documents; these are accessible via the app's `EMA_CORPUS_PATH` only if the corpus JSONL is rebuilt to include them — but currently the PDF corpus records come from accordion-extracted Q&As that happen to cite PDFs, not from `parsed_pdfs` directly.

---

## Architecture of current retrieval path

```
chat UI query
  → harness/embed.py build_index(corpus_path)
  → FAISS index from corpus JSONL records
  → top-K results shown in UI
```

The index is pre-built and stored in `harness/index/`. The index size (639 KB docstore, 639 KB FAISS vectors) confirms it was built from mini_corpus (156 records), not the full corpus.

---

## What needs to change

| Priority | Fix | Scope |
|----------|-----|-------|
| P0 | Change default corpus to `corpus.jsonl` in both `embed.py` and `app.py` | 2-line change |
| P0 | Delete/rebuild the FAISS index from full corpus | Operational |
| P1 | Document `EMA_CORPUS_PATH` env var in SETUP.md | Docs |
| P2 | Run corpus extractor against the ~2,797 missing accordion pages | Phase 1 |
| P3 | Re-examine which ema-inpage-item pages contain real Q&A content worth extracting | Phase 1 |

---

## Files to touch

- **`harness/embed.py:34`** — change `DEFAULT_CORPUS` to `corpus.jsonl`
- **`app.py:32`** — change `DEFAULT_CORPUS` to `corpus.jsonl`
- **`docs/SETUP.md`** — document `EMA_CORPUS_PATH`, note index rebuild
- **`corpus/build_corpus.py`** (P2) — re-run to capture missing accordion pages
