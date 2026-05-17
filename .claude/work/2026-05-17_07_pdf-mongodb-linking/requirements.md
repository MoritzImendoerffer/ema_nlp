# Requirements: PDF parsed cache → MongoDB linking

## Functional requirements

1. Verify that `extract_pdf_text_pymupdf.py` was executed and `parsed_pdf.pkl` files exist
2. Understand the mapping between Scrapy cache directories and MongoDB `web_items` documents
3. Design a way to associate parsed PDF content (markdown, json) with MongoDB records
4. Respect Nextcloud-based file sync — local paths are acceptable as a linking mechanism

## Non-functional requirements

- Must not bloat `web_items` collection unnecessarily
- Must support the Phase 1 corpus extraction pipeline (TASK-007)
- Should be easy to rebuild if parsing is re-run
- Should be queryable by URL

## Out of scope

- Re-running PDF extraction
- Storing raw PDF binaries in MongoDB
- Cloud object storage (Nextcloud is the sync layer)
