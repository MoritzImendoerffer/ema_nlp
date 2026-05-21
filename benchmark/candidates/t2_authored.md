# T2 Scoping — Benchmark Candidates

Questions that require correct identification of the relevant procedure or document
among topically-adjacent EMA Q&A sources. Each item lists the correct Q&A plus
"distractor" Q&As that share keywords but answer a different scope.

All 10 questions below are accepted for `benchmark.jsonl` (bench_ids T2-001–T2-010).

---

## T2-001: Which referral uses the PRAC as lead assessment committee?

**Question:** Which EMA referral procedure uses the PRAC as the lead scientific assessment committee?

**Correct answer Q&A:** Article 31 pharmacovigilance referral Q16 (qa_id: `685a68deecc58167`)
- PRAC leads assessment; appoints (co-)rapporteurs; issues recommendation forwarded to CHMP/CMDh

**Distractor Q&As:**
- Art30 Q12 (`d48b50efeb30f114`) — CHMP leads; similar structure but wrong committee
- Art31NPV Q16 (`c941de2b357028ec`) — CHMP leads (CHMP, not PRAC)

**Why T2:** Retriever must distinguish "pharmacovigilance referral → PRAC" from "other referrals → CHMP" even though all three Q&As discuss the same referral assessment structure.

---

## T2-002: Which referral always charges fees regardless of initiator?

**Question:** In which EMA referral procedure are fees always levied by the Agency regardless of who initiated the procedure?

**Correct answer Q&A:** Article 31 pharmacovigilance referral Q13 (qa_id: `17ff70246e10eab5`)
- Agency always levies fee; share calculated via Art57 database; SME reduction if declared within 30 days

**Distractor Q&As:**
- Art30 Q9 (`c288d5048938d329`) — fee only if MAH initiated
- Art31NPV Q13 (`93c4d3066dbff973`) — fee only if MAH/applicant initiated

**Why T2:** Fee conditionality differs by procedure; a retriever that conflates Art31PV with other Art31/Art30 referrals will retrieve the wrong fee rule.

---

## T2-003: Default contact person for Art31 PV referral

**Question:** Who is the default contact person for an MAH receiving EMA correspondence in an Article 31 pharmacovigilance referral?

**Correct answer Q&A:** Article 31 pharmacovigilance referral Q10 (qa_id: `dc5dc6d5a6a1c10a`)
- QPPV is default contact

**Distractor Q&As:**
- Art31NPV Q10 (`38c0a2b96fe43f13`) — regulatory contact point in EudraVigilance (not QPPV)
- Art30 Q6 (`127ae26a28b5a9b7`) — MAH designates a contact person

**Why T2:** Default contact person differs between procedures; only Art31PV uniquely defaults to the QPPV.

---

## T2-004: Which procedure addresses divergent national decisions?

**Question:** Which specific EMA referral procedure applies when Member States have adopted divergent authorisation decisions for the same nationally authorised medicinal product?

**Correct answer Q&A:** Article 30 referral Q1 (qa_id: `15aec2b3a08c2f0f`)
- "harmonisation" referral specifically for divergent national decisions

**Distractor Q&As:**
- Art31NPV Q1 (`b0c3ed75f1bc447c`) — Union interests + quality/efficacy data
- Art31PV Q1 (`90d386aaaf422e29`) — Union interests + pharmacovigilance data

**Why T2:** Trigger condition is the scoping criterion. "Divergent national decisions" maps uniquely to Art30; Art31 referrals require "Union interests".

---

## T2-005: Shorter initial assessment period — 30 vs 60 days

**Question:** What is the standard initial active-day assessment period that distinguishes Article 31 pharmacovigilance referrals from Article 30 and Article 31 non-pharmacovigilance referrals?

**Correct answer Q&A:** Article 31 pharmacovigilance referral Q21 (qa_id: `1408e2bba6739c76`)
- 30 days (PRAC); extendable to 60 days

**Distractor Q&As:**
- Art30 Q17 (`112b7496bd326b08`) — 60 days
- Art31NPV Q21 (`7f0118fa3de1cfa5`) — 60 days

**Why T2:** PRAC timetable starts at 30 days vs 60 days for CHMP-led referrals. Retriever conflating all referral types will return the wrong timeline.

---

## T2-006: Which Art31 sub-type handles pharmacovigilance safety signals?

**Question:** An EMA referral is being initiated following new post-marketing safety signals from pharmacovigilance data for an authorised product. Which Article 31 referral sub-type is applicable?

**Correct answer Q&A:** Article 31 pharmacovigilance referral Q2 (qa_id: `581d7858e7681dde`)
- Art31PV: Union interests + pharmacovigilance data; Article 107i criteria not met

**Distractor Q&As:**
- Art31NPV Q2 (`0192042f9793763d`) — non-pharmacovigilance data (quality/efficacy)
- Art30 Q2 (`75b3489bc1c0bde6`) — divergent national decisions

**Why T2:** "Pharmacovigilance data" is the key trigger for Art31PV; confusing it with Art31NPV gives wrong procedure.

---

## T2-007: CAP notification in Art31 PV vs NPV

**Question:** When a centrally authorised product (CAP) is included in an Article 31 pharmacovigilance referral, who at the MAH is specifically notified by EMA?

**Correct answer Q&A:** Article 31 pharmacovigilance referral Q12 (qa_id: `641b8c6dedce4867`)
- QPPV is notified (all QPPVs for all products in scope)

**Distractor Q&A:**
- Art31NPV Q12 (`ec6141489defdde1`) — MAH (not QPPV) is notified

**Why T2:** For CAPs, Art31PV notifies QPPV; Art31NPV notifies MAH. Same "CAP in Art31 referral" question but different notification recipient depending on procedure sub-type.

---

## T2-008: Narrow vs broad product scope in Art30 vs Art31

**Question:** For which referral procedure is the scope of included medicinal products limited exclusively to the product(s) for which divergent national decisions were adopted?

**Correct answer Q&A:** Article 30 referral Q5 (qa_id: `7f41fce3f3e7b08a`)
- Only the concerned product with divergent national decisions

**Distractor Q&As:**
- Art31PV Q5 (`f881ba0332c94c1a`) — all EEA products affected by safety concern
- Art31NPV Q5 (`2b3ffd6f9c69a059`) — all EEA products affected by the concern

**Why T2:** Art30 has narrow product scope (specific product); Art31 referrals have broad scope (all affected products). Retriever must identify the Art30-specific constraint.

---

## T2-009: MAH grouping in Art31 NPV regardless of company affiliation

**Question:** Can MAHs from different company groups pool their responses and present a single consolidated submission in an Article 31 non-pharmacovigilance referral?

**Correct answer Q&A:** Article 31 NPV referral Q11 (qa_id: `22ee1f39f7ba4413`)
- Yes, regardless of group/company affiliation

**Distractor Q&As:**
- Art31PV Q11 (`661e9be3ea97cd59`) — same rule, different source document
- Art30 Q10 (`dc72d3601946df60`) — MAH submits information but no explicit grouping rule mentioned

**Why T2:** Though Art31PV has the same rule, a question framed specifically for Art31NPV should retrieve the Art31NPV document. Tests that the retriever correctly scopes to the named procedure.

---

## T2-010: Fee conditionality — Art30 + Art31NPV vs Art31PV

**Question:** Under which EMA referral procedures are fees payable only when the MAH or applicant was the one who initiated the referral?

**Correct answer Q&As:** 
- Article 30 Q9 (qa_id: `c288d5048938d329`) — fee only if MAH initiated
- Article 31 NPV Q13 (qa_id: `93c4d3066dbff973`) — fee only if MAH/applicant initiated

**Distractor Q&A:**
- Art31PV Q13 (`17ff70246e10eab5`) — fee always charged regardless of initiator

**Why T2:** Requires identifying BOTH Art30 and Art31NPV as having conditional fees, as opposed to Art31PV. Tests correct multi-document scoping where two procedures share a rule and one does not.

---

*Generated 2026-05-20 as part of TASK-011 benchmark construction.*
