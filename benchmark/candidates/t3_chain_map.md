# T3 Multi-hop — Chain Map

Each T3 question requires traversing a chain of 2+ Q&As to construct a complete answer.
No single Q&A suffices. The chain structure simulates the `cross_refs` traversal that
the full corpus enables; here chains are identified semantically across the mini corpus.

All 10 chains below are included in `benchmark.jsonl` as bench_ids T3-001–T3-010.

---

## T3-001: Worksharing mixed variation type → timetable rule

**Question:** If an MAH submits a worksharing procedure combining Type IB and Type II variations, what assessment timetable applies and what constraint governs which MAs can be included?

```
Hop 1: Worksharing Q1 (4fd6d02218d63a99)
  "What is worksharing and what types of variations can be subject to worksharing?"
  → Establishes: Type IB and II can be workshared; all MAs must belong to same MAH or group

Hop 2: Worksharing Q7 (6d008e215c083434)
  "How will variation applications under worksharing be handled (timetable)?"
  → Establishes: timetable follows the highest variation type in the group = Type II = 60 days

Chain: Which variations qualify? → What timetable applies to a mixed group?
```

---

## T3-002: Art30 opinion → Commission Decision chain

**Question:** Following an Article 30 referral, after the CHMP adopts its final opinion, what process leads to a legally binding decision for all Member States?

```
Hop 1: Art30 Q23 (48a3d97325d76b0d)
  "When will the CHMP opinion be issued?"
  → Establishes: CHMP opinion within 60–150 days of start

Hop 2: Art30 Q30 (38acf51051f28365)
  "What happens after the final opinion of the CHMP on the Article 30 referral?"
  → Establishes: Agency + MAH + NCAs finalise translations → sent to EC → binding EC Decision

Chain: CHMP opinion timeline → post-opinion binding decision process
```

---

## T3-003: Art31PV PRAC recommendation → CHMP opinion

**Question:** In an Article 31 pharmacovigilance referral, what happens after the PRAC issues its final recommendation, and which committee issues the final regulatory opinion?

```
Hop 1: Art31PV Q32 (0858ffb6dc5282e4)
  "What happens after the PRAC recommendation?"
  → Establishes: final PRAC recommendation (after any re-examination) sent to CHMP/CMDh

Hop 2: Art31PV Q33 (524f367515ea1f87)
  "When will the CHMP issue an opinion/CMDh reach a position?"
  → Establishes: CHMP/CMDh considers at next plenary; aims to adopt at first meeting

Chain: PRAC recommendation finalisation → CHMP/CMDh final opinion step
```

---

## T3-004: Extension grouping condition → co-rapporteur + timeline

**Question:** For an extension application grouped with a type-II variation for a new indication, is the CHMP co-rapporteur involved and what is the total assessment timeline?

```
Hop 1: Extensions Q4 (b46c1e28c85f57dc)
  "Is the (co-)rapporteur involved in extension applications?"
  → Establishes: co-rapporteur normally NOT involved; EXCEPTION: grouped with type-II for new indication → normally IS involved

Hop 2: Extensions Q12 (152578642b610fdf)
  "How shall my extension application be handled (timetable)?"
  → Establishes: 210 days (less clock-stops) — same as initial MAA

Chain: Grouping condition (co-rapporteur exception) → timeline for grouped extension
```

---

## T3-005: Art31PV — who assesses → who issues final opinion

**Question:** Who performs the scientific assessment in an Article 31 pharmacovigilance referral, and which committee receives the output to issue the final regulatory position?

```
Hop 1: Art31PV Q16 (685a68deecc58167)
  "Who will perform the assessment?"
  → Establishes: PRAC leads; (co-)rapporteurs appointed; PRAC issues recommendation → forwarded to CHMP (or CMDh)

Hop 2: Art31PV Q33 (524f367515ea1f87)
  "When will the CHMP issue an opinion/CMDh reach a position?"
  → Establishes: CHMP/CMDh adopts at next plenary meeting after PRAC recommendation

Chain: PRAC assessment output → CHMP/CMDh receives it → issues final opinion
```

---

## T3-006: Worksharing timetable → unfavourable opinion → re-examination

**Question:** If an MAH receives an unfavourable CHMP opinion in a worksharing procedure, what options are available and what deadlines govern them?

```
Hop 1: Worksharing Q7 (6d008e215c083434)
  "How will variation applications under worksharing be handled (timetable)?"
  → Establishes: procedure follows Type II timetable (60 days); leads to CHMP opinion

Hop 2: Worksharing Q8 (26079c43d6a60f60)
  "How and when will the MAs be updated following a worksharing procedure?"
  → Establishes: MAH may give written notice within 15 days requesting re-examination;
    Article 9(2) Regulation 726/2004 applies

Chain: When does the opinion arrive (timetable) → what can MAH do within 15 days
```

---

## T3-007: Art31PV product scope → who assesses

**Question:** Which medicinal products are included in an Article 31 pharmacovigilance referral, and which committee is responsible for their scientific assessment?

```
Hop 1: Art31PV Q5 (f881ba0332c94c1a)
  "Which medicinal products can be involved in an Article 31 pharmacovigilance referral?"
  → Establishes: all EEA products with valid MA affected by safety concern (NAP + CAP)

Hop 2: Art31PV Q16 (685a68deecc58167)
  "Who will perform the assessment?"
  → Establishes: PRAC leads assessment with (co-)rapporteurs

Chain: Scope of products in procedure → who assesses those products
```

---

## T3-008: Worksharing submission channel (mixed CAP/NAP) → post-opinion MA updates

**Question:** For a worksharing application covering CAPs and NAPs, how should the submission be made and what happens after a favourable CHMP opinion regarding Commission Decision?

```
Hop 1: Worksharing Q5 (ea52d379ee400295)
  "How and to whom shall I submit my variation application under worksharing?"
  → Establishes: submit via eSubmission Gateway to EMA; for mixed NAP+CAP, Gateway delivery = delivery to all CAs

Hop 2: Worksharing Q8 (26079c43d6a60f60)
  "How and when will the MAs be updated following a worksharing procedure?"
  → Establishes: after favourable opinion, where Commission Decision required for CAPs → Agency informs Commission; 15-day re-examination window; then Commission Decision process

Chain: Submission channel for mixed CAP/NAP → post-opinion process for Commission Decision
```

---

## T3-009: CAP notification in Art31PV → PRAC leads assessment

**Question:** When a centrally authorised product is involved in an Article 31 pharmacovigilance referral, who is notified by EMA and who then leads the scientific assessment?

```
Hop 1: Art31PV Q12 (641b8c6dedce4867)
  "What happens if centrally authorised products are involved in the procedure?"
  → Establishes: QPPV notified by Agency; EPAR page announcement linked

Hop 2: Art31PV Q16 (685a68deecc58167)
  "Who will perform the assessment?"
  → Establishes: PRAC leads assessment

Chain: Who is notified for CAPs → who performs the assessment
```

---

## T3-010: Herbal traditional use requirement → EEA countries count as "within Union"

**Question:** For traditional herbal medicinal product registration, can medicinal use in EEA countries outside the EU (Iceland, Liechtenstein, Norway) count towards the required 15-year period within the Union?

```
Hop 1: Herbal R10 (fd6eabdbb2024241)
  "(R10) Are herbal medicinal products which fulfil the medicinal use requirement of 30 years... eligible?"
  → Establishes: need at least 30 years total, including at least 15 years within the Union

Hop 2: Herbal R11 (154c375fa979528c)
  "(R11) Are herbal medicinal products with medicinal use in Iceland, Liechtenstein and Norway...?"
  → Establishes: EEA non-EU countries count; use "within the Union" includes EEA members

Chain: General rule (15 years within Union) → does EEA non-EU use qualify?
```

---

*Generated 2026-05-20 as part of TASK-012 benchmark construction.*
