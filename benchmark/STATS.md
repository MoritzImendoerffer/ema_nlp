# Benchmark Statistics — v1

Generated: 2026-05-20

## Type distribution

| Type | Count | Target | Status |
|------|-------|--------|--------|
| T1 Lookup | 20 | 20 | ✓ |
| T2 Scoping | 10 | 10 | ✓ |
| T3 Multi-hop | 10 | 10 | ✓ |
| T4 Synthesis | 5 | ≥5 | ✓ |
| **Total** | **45** | **≥45** | **✓** |

## Source diversity

| Source document | Items |
|----------------|-------|
| Article 30 referral procedures Q&A | 12 |
| Article 31 pharmacovigilance referrals Q&A | 14 |
| Article 31 non-pharmacovigilance referrals Q&A | 10 |
| Extensions of marketing authorisations Q&A | 7 |
| Worksharing Q&A | 6 |
| Herbal medicinal products Q&A | 4 |
| Ancillary medicinal substances (medical devices) Q&A | 1 |

*(Note: items can reference multiple sources; counts include all gold_sources)*

**Distinct source URLs: 7**

## Gold Q&A ID coverage

- Total benchmark items: 45
- Items with a single gold_qa_id (T1): 20
- Items with multiple gold_qa_ids (T2/T3/T4): 25
- Items spanning ≥2 distinct source documents (T4): 5
- Total unique gold_qa_ids referenced: 55 (some shared across items)

## Contamination resistance

| Feature | Count | % |
|---------|-------|---|
| Questions with specific numeric thresholds | 28 | 62% |
| T3/T4 multi-hop (harder to memorize) | 15 | 33% |
| T4 composite/counterfactual items | 5 | 11% |

All T1 items were selected for numeric specificity (days, months, years) where possible.
T4-005 is explicitly composite (combines herbal use rules with worksharing fee rules —
no single EMA Q&A document covers this combination).

## Topic coverage

| Topic area | Items | Source |
|-----------|-------|--------|
| Post-authorisation referral procedures | 26 | Art30 + Art31PV + Art31NPV |
| Variations (worksharing + extensions) | 13 | Worksharing + Extensions Q&A |
| Herbal medicinal products | 4 | Herbal Q&A |
| Medical devices / ancillary substances | 1 | Ancillary Q&A |

## Notes

- Mini corpus (156 records from 7 EMA pages) used as source. Full corpus (26K records
  in MongoDB) contains additional Q&As from nitrosamines, impurities, generics etc.
  Benchmark v2 should sample from the full corpus for wider topic coverage.
- No cross_ref chains were present in the mini corpus; T3 chains were identified
  semantically across the 7 source documents.
- zero_shot_known field populated to {} — populate after benchmark finalisation via
  closed-book runs through the eval runner (`scripts/run_eval.py`; the Phase 2.5
  contamination screen is still TODO).
