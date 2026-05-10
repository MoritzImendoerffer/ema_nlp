# Phase 0 Execution — Decisions & Findings

**Date:** 2026-05-10  
**Tasks completed:** TASK-001, TASK-002, TASK-003 (partial — awaiting SME decision)  
**Script:** `scripts/phase0_inventory.py`, `scripts/phase0_topic_report.py`, `scripts/phase0_scope_decision.ipynb`

---

## TASK-001 — MongoDB Q&A Inventory

### What was done
Queried `ema_scraper.web_items` (115,101 total docs) for:
- HTML pages with accordion Q&A structure (class `accordion-item`)
- PDFs whose URLs match Q&A categories and Q&A keywords

### Key decisions

**HTML accordion class:** The outer wrapper uses `class="accordion"` (count=1 per page) but individual Q&A items use `class="accordion-item"` (17 per page in a typical section). Initial implementation used the wrong class, producing `q_count_estimate=1` for all pages. Fixed to `accordion-item`.

**Q&A signal filter:** Kept only HTML pages that have either a Q&A keyword in the URL (`questions`, `q-and-a`, `guidance`) *or* ≥5 accordion items. This removes navigation pages with one or two accordions that are menus rather than Q&A content.

**Veterinary exclusion:** Applied URL-segment exclusions (`veterinary`, `vet-`, `animal-health`) at the start of both HTML and PDF scans. No exceptions made — EMA vet content has a separate regulatory track and different terminology.

**Human-regulatory scope guard (HTML):** Required at least one of seven URL path prefixes (`/en/human-regulatory`, `/en/research-development`, `/en/post-authorisation`, etc.). This is conservative — some cross-cutting documents under `/en/documents/other` are included via the `other` entry.

**PDF Q&A keyword list:** Matched against URL slugs only (no text search, since PDFs have no text in MongoDB). Six keywords: `questions-and-answers`, `questions-answers`, `q-and-a`, `question-and-answer`, `question-answers`, `qa-`. Intentionally broad; Phase 1 PDF extractor will filter further by content.

### Results
| Metric | Value |
|--------|-------|
| HTML pages scanned | 21,240 |
| HTML accordion Q&A pages found | 64 |
| PDFs scanned | 58,232 |
| Q&A PDFs found | 101 |
| Total sources | 165 |
| Estimated Q&A pairs (HTML) | 1,506 |

---

## TASK-002 — Topic Stratification & Cross-reference Analysis

### What was done
- Assigned each of the 165 sources to one of 11 topic clusters using URL keyword matching
- Counted estimated Q&A pairs per cluster
- Scanned all 64 HTML pages for cross-references: text patterns (`see Q&A N`) and hyperlinks to other EMA Q&A pages
- Computed chain completeness: fraction of hyperlink targets that exist in our inventory

### Key decisions

**Cluster definitions from URL only:** No text analysis was done for clustering in Phase 0 — URL path segments contain sufficient signal. Phase 1 may revisit with topic modelling over extracted text.

**Cluster assignment priority:** CLUSTERS list is ordered most-specific-first. A COVID-19 page that also contains "pharmacovigilance" in the URL falls into COVID-19, not Pharmacovigilance. This is intentional — COVID content is thematically distinct even if it uses PV terminology.

**Thin cluster threshold = 5 Q&A pairs:** Two clusters are thin (Safety & Excipients PDF, Regulatory & Procedural PDF) because their sources are PDF-only and we can't count Q&A pairs without text. These are *not* thin by content — they will likely contribute substantial pairs after Phase 1 PDF extraction.

**Cross-reference scope:** Text-pattern xrefs (`see Q&A N`) and hyperlink xrefs counted separately. Hyperlinks are higher fidelity for chain completeness; text patterns may be false positives (quoted in context, not actual navigation). Only hyperlinks used for chain completeness %.

**Chain completeness = 43.6%:** This is acceptable for Phase 0 for two reasons:
1. PDFs are not yet text-extracted — many xref targets live in PDFs that *are* in our inventory (101 docs)
2. Some targets are product-specific EPAR pages deliberately out of scope

Action: re-run chain completeness after Phase 1 PDF extraction; target ≥60%.

**T3 multi-hop constraint:** T3 benchmark questions must be drawn from cross-reference chains where *both* source and target are in-corpus. Currently 17 in-corpus hyperlink pairs confirmed. This is the upper bound for T3 questions until Phase 1 expands the corpus.

### Results
| Cluster | HTML | PDF | Est. Q&A (HTML) |
|---------|------|-----|-----------------|
| Research & Dev / Pre-auth | 16 | 63 | 492 |
| Post-auth: Referral Procedures | 8 | 9 | 272 |
| Post-auth: Other | 13 | 1 | 231 |
| Post-auth: Pharmacovigilance & Safety | 8 | 1 | 129 |
| Other / Uncategorised | 3 | 5 | 155 |
| COVID-19 & Public Health | 7 | 0 | 93 |
| Post-auth: Variations & Extensions | 7 | 0 | 112 |
| Herbal & Traditional Medicines | 1 | 0 | 14 |
| Medical Devices | 1 | 0 | 8 |
| Regulatory & Procedural (PDF) | 0 | 15 | 0 ⚠️ |
| Safety & Excipients (PDF) | 0 | 7 | 0 ⚠️ |

Cross-reference pages: 25/64 (39%) | Chain completeness: 43.6% (17/39 links)

---

## TASK-003 — Go/No-go Decision Notebook

### What was done
Generated `scripts/phase0_scope_decision.ipynb` with three figures and a Decision cell.

### Key decisions

**Static figures, live data:** Figures 1 and 2 are computed from the live CSV at notebook run time. Figure 3 (chain completeness) uses hardcoded numbers from the TASK-002 output — updating requires re-running `phase0_topic_report.py` first.

**No auto-decision:** Claude does not fill in the GO/NO-GO — that is an explicit SME gate. All Phase 1 tasks are blocked in state.json until TASK-003 is committed with a decision.

### What you need to do
1. Open `scripts/phase0_scope_decision.ipynb`
2. Run all cells
3. Fill the **✏️ DECISION** cell with GO/NO-GO + rationale
4. Commit: `git add scripts/phase0_scope_decision.ipynb && git commit -m 'TASK-003: Phase 0 go/no-go decision — GO'`

---

## Open questions / risks surfaced

| Risk | Severity | Mitigation |
|------|----------|------------|
| PDF text not in MongoDB — 101 PDFs have only URL, no content | High | Phase 1 TASK-006 PDF extractor must fetch and parse PDFs from EMA URLs |
| Chain completeness 43.6% limits T3 multi-hop questions | Medium | Re-measure after PDF extraction; T3 pool may be 17→60+ pairs |
| "Other / Uncategorised" cluster (155 Q&A pairs) needs review | Low | Inspect those 3 HTML + 5 PDF sources manually in Phase 1 |
| Two thin PDF clusters show 0 Q&A pairs in Phase 0 | Low | Expected — PDF text extraction will populate counts |
