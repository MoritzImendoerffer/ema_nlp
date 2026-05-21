# Few-Shot Exemplars for EMA Q&A RAG System

Version: v1  
Generated: 2026-05-20  
Used by: all three model tiers (identical prompt across tiers)

These examples are **held-out** — none of the Q&As used here appear as gold answers
in `benchmark/benchmark.jsonl`. They demonstrate the expected reasoning trace for
each question type.

---

## Example 1 — T1 Lookup

**Question:** What dosages of vitamins and minerals are acceptable in traditional herbal medicinal products eligible for simplified registration?

**Retrieved Q&A [relevant, score 2]:**
```
Source: Herbal medicinal products: questions and answers
qa_id: 55391af71237e01c

Q: (R4) What dosages of vitamins and minerals are acceptable in traditional herbal medicinal products eligible for simplified registration?

A: Article 16a(2) of Directive 2001/83/EC states that the presence in the herbal medicinal product of vitamins and minerals for the safety of which there is well-documented evidence shall not prevent the product from being eligible for registration, provided that the action of the vitamins or minerals is ancillary to that of the herbal active ingredients regarding the specified claimed indication(s). The pharmaceutical legislation does not impose any limitation to the dosage of vitamins and minerals; however, the vitamin and mineral content must not exceed the commonly accepted safe dose levels and the action of vitamins or minerals must be ancillary to that of the herbal active ingredients.
```

**SME reasoning trace:**
- The question asks for a specific regulatory limit on vitamin/mineral dosages.
- The retrieved Q&A directly addresses the question using the applicable legislation (Article 16a(2) of Directive 2001/83/EC).
- The key answer elements are: (1) no specific dosage limit in legislation, (2) must not exceed commonly accepted safe dose levels, (3) must be ancillary to herbal active ingredients.
- T1 Lookup: single source Q&A answers the question completely.

**Answer:**
Under Article 16a(2) of Directive 2001/83/EC, no specific dosage limit is imposed on vitamins and minerals in traditional herbal medicinal products eligible for simplified registration. However, the vitamin/mineral content must not exceed commonly accepted safe dose levels, and their action must be ancillary to that of the herbal active ingredients for the specified claimed indication.

**Citation:** Herbal medicinal products Q&A, question R4. Source: https://www.ema.europa.eu/en/human-regulatory-overview/herbal-medicinal-products/herbal-medicinal-products-questions-answers

---

## Example 2 — T1 Lookup (negative/restrictive answer)

**Question:** Is it acceptable to reference "organic farming" in the labelling of a herbal medicinal product?

**Retrieved Q&A [relevant, score 2]:**
```
Source: Herbal medicinal products: questions and answers
qa_id: f3fdeed6240a95f0

Q: (R5) Is reference to "organic farming" acceptable in either the labelling or in the package leaflet of a herbal medicinal product?

A: Article 62 of Directive 2001/83/EC states that the outer packaging and the package leaflet may include symbols or pictograms designed to clarify certain information and other information compatible with the summary of product characteristics useful to the patient, to the exclusion of any element of a promotional nature. Having regard to the position adopted by the Pharmaceutical Committee in March 2000 on this matter, the HMPC is of the opinion that the reference to "organic farming" must be regarded as promotional and therefore is not acceptable in either the labelling or in the package leaflet of a herbal medicinal product.
```

**SME reasoning trace:**
- The question asks whether "organic farming" references are permitted in labelling.
- The retrieved Q&A gives a clear "No" with legal basis (Article 62 of Directive 2001/83/EC).
- The HMPC position is that "organic farming" references are promotional in nature and therefore not acceptable.
- T1 Lookup: a single Q&A provides a definitive regulatory position.

**Answer:**
No. Reference to "organic farming" is not acceptable in either the labelling or the package leaflet of a herbal medicinal product. The HMPC considers such references promotional in nature, which is prohibited under Article 62 of Directive 2001/83/EC.

**Citation:** Herbal medicinal products Q&A, question R5. Source: https://www.ema.europa.eu/en/human-regulatory-overview/herbal-medicinal-products/herbal-medicinal-products-questions-answers

---

## Example 3 — T2 Scoping

**Question:** For an EU herbal monograph listing preparations with "well-established medicinal use" indications, what must an applicant demonstrate to relate their product to that monograph?

**Retrieved Q&As:**

```
[Relevant, score 2] Source: Herbal medicinal products: questions and answers
qa_id: 7b3edd23c93f0c3e

Q: (R7) How can I relate my product to a EU herbal monograph where herbal preparations are listed and have 'well established medicinal use' indications?

A: Where the EU herbal monograph refers to 'well established medicinal use', herbal preparations with a specific posology will be stated. The specific herbal preparation listed will have been shown to be effective in published clinical studies for the stated indication. The applicant therefore will need to demonstrate that the proposed product contains a herbal preparation which is 'similar' to the preparation listed in the monograph. To demonstrate comparability the applicant would need to address the equivalence/similarity of the herbal preparation used in the clinical studies to the herbal preparation in the product.
```

```
[Marginally relevant, score 1] Source: Herbal medicinal products: questions and answers
qa_id: 967e13b50c493279

Q: (R8) How can I relate my product to an EU herbal monograph where herbal preparations are listed with 'traditional medicinal use' indications?

A: Where the EU herbal monograph refers to 'traditional medicinal use', specific herbal preparations with a specific posology will be stated. The applicant will need to demonstrate that the proposed product contains a herbal preparation which 'corresponds' to the preparation listed in the monograph.
```

**SME reasoning trace:**
- The question specifically asks about "well-established medicinal use" monographs.
- Q&A R7 (qa_id: 7b3edd23) directly addresses this — the applicant must demonstrate "similarity" to the listed preparation.
- Q&A R8 (qa_id: 967e13b5) addresses "traditional medicinal use" monographs, which use different criteria ("corresponds" vs "similar"). It is a distractor — same topic area but different scope.
- T2 Scoping: retriever correctly surfaces R7 as most relevant; R8 is adjacent but wrong scope (traditional use vs well-established use). The answer must use only R7.

**Answer:**
For EU herbal monographs listing preparations with "well-established medicinal use," the applicant must demonstrate that their proposed product contains a herbal preparation which is "similar" to the preparation listed in the monograph. This requires addressing the equivalence or similarity of the herbal preparation used in the clinical studies cited in the monograph to the herbal preparation in the applicant's product.

Note: This is distinct from "traditional medicinal use" monographs (R8), where the applicant need only show the preparation "corresponds" to the monograph entry — a less stringent comparability requirement.

**Citation:** Herbal medicinal products Q&A, question R7. Source: https://www.ema.europa.eu/en/human-regulatory-overview/herbal-medicinal-products/herbal-medicinal-products-questions-answers

---

## Example 4 — T3 Multi-hop

**Question:** How should an MAH submit a type IB variation for an ancillary medicinal substance in a medical device, and when should they submit the initial letter of intent before any consultation?

**Retrieved Q&As (in chain order):**

```
[Relevant for hop 1, score 2] Source: Consultation procedure for ancillary medicinal substances in medical devices
qa_id: aec4660a01b848ba

Q: 1.1 How and when should I submit "a letter of intent" for an initial consultation on an ancillary medicinal substance/ancillary human blood derivative incorporated in a medical device?

A: Please notify the Agency of the intention to submit an application for an initial consultation on an ancillary medicinal substance by sending "a letter of intent" at least 6 months before the expected date of submission. Please send "the letter of intent" by raising a ticket via EMA Service Desk, selecting the tab "Business Services", category "Human Regulatory". The subcategory to be selected is "Pre-Submission Phase - Human", followed by the sub-option: "Letter of intent".
```

```
[Relevant for hop 2, score 2] Source: Consultation procedure for ancillary medicinal substances in medical devices
qa_id: d1fd903fc94e43c1

Q: 2.1 How and when should I submit my type IA, IB or type II variation for an ancillary medicinal substance or ancillary human blood derivative incorporated in the medical device?

A: The eSubmission Gateway and the eSubmission Web Client are mandatory submission channels for the submission of applications to EMA (including Supplementary information requested during validation). Type IA, IB or type II variations for an ancillary medicinal substance or ancillary human blood derivative incorporated in a medical device must be submitted using the eSubmission Gateway or the eSubmission Web Client.
```

**SME reasoning trace:**
- The question has two parts: (1) how to submit a type IB variation; (2) when to submit the letter of intent for consultation.
- Hop 1: Q&A 1.1 answers the letter of intent timing (at least 6 months before expected submission date, via EMA Service Desk).
- Hop 2: Q&A 2.1 answers the submission method for variations (eSubmission Gateway or Web Client — mandatory).
- T3 Multi-hop: neither Q&A alone answers the full question; both must be synthesised.

**Answer:**
Two steps apply:

1. **Letter of intent** (for the initial consultation, before the variation): Submit at least **6 months** before the expected submission date, via the EMA Service Desk (Business Services → Human Regulatory → Pre-Submission Phase - Human → Letter of intent).

2. **Type IB variation submission**: Use the **eSubmission Gateway** or **eSubmission Web Client** — both are mandatory submission channels for variations related to ancillary medicinal substances in medical devices.

**Citations:**
- Q 1.1 (letter of intent): Consultation procedure for ancillary medicinal substances Q&A
- Q 2.1 (type IB variation submission): same source
Source: https://www.ema.europa.eu/en/human-regulatory-overview/medical-devices/consultation-procedure-ancillary-medicinal-substances-medical-devices

---

## Example 5 — T1 Lookup with conditional answer

**Question:** Are medicinal products that have been extensively used for 10 years in Switzerland (but not in the EU) eligible for traditional-use registration in the EU?

**Retrieved Q&A [relevant, score 2]:**
```
Source: Herbal medicinal products: questions and answers
qa_id: a3f3ac3dfb48ea6f  [held-out — not in benchmark]

Q: (R14) Can the data which formed the basis for the granting of a Swiss marketing authorisation be used to demonstrate extensive use for the purpose of traditional-use registration?

A: Swiss marketing authorisation data may be used to demonstrate extensive use, provided the product has been extensively used for that period within Switzerland. Where relevant, the prevalence of use and/or the sales data or prescribing data could be included to demonstrate the extent of use.
```

**SME reasoning trace:**
- The question asks whether Swiss use specifically counts for traditional-use registration.
- The retrieved Q&A (R14) directly addresses this: Swiss MA data can be used to demonstrate extensive use.
- Important nuance: Swiss data counts for the "30-year total" period but NOT for the "15-year within the Union" requirement, since Switzerland is not an EU/EEA member state.
- T1 Lookup with conditional answer: the direct Q&A is relevant but the answer requires the regulatory framework context (30/15-year split from R10) to be fully accurate.

**Answer:**
Swiss marketing authorisation data may be used to demonstrate extensive use for the **30-year total** period required for traditional-use registration (Article 16c(1)(c) of Directive 2001/83/EC). However, since Switzerland is not an EU or EEA Member State, Swiss use does **not** count towards the **15-year period within the Union** requirement — this must be fulfilled by EU/EEA use separately.

**Citation:** Herbal medicinal products Q&A, question R14 (and R10 for the 30/15-year framework). Source: https://www.ema.europa.eu/en/human-regulatory-overview/herbal-medicinal-products/herbal-medicinal-products-questions-answers

---

## Usage notes

- Use these examples in the system prompt or few-shot section to demonstrate the expected output format.
- The reasoning trace is internal — strip it from the user-facing response.
- Always include the citation with source URL.
- If retrieved Q&As score 0 (not relevant), do not use them in the answer — say "I could not find a directly relevant EMA Q&A for this question."
- For T2 questions, always note which adjacent Q&As were considered and why they do not apply.
