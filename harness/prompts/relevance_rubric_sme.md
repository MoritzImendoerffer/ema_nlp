# EMA Q&A Relevance Rubric — v1
# Used by harness/ablations/a3_reranker.py for LLM-based reranking.

A retrieved EMA Q&A record is **relevant** to a query if ALL of the following hold:

1. **Procedural match** — The retrieved Q&A addresses the same regulatory procedure or obligation as the query. A Q&A about post-marketing commitments is not relevant to a question about initial MAA requirements, even if both mention the same product type.

2. **Scope alignment** — The retrieved Q&A applies to the same scope as the query:
   - Product type: chemical vs. biological vs. ATMPs vs. generics — cross-type Q&As are not relevant unless explicitly stated to apply broadly.
   - Authorisation route: CAP (centralised) vs. NAP (national/MRP/DCP) — do not mix unless the Q&A explicitly covers both.
   - Party: MAH obligations vs. applicant obligations are different procedural steps. A Q&A answering "what must the applicant submit?" is not relevant to "what must the MAH maintain?"

3. **Threshold specificity** — If the query asks for a specific numerical limit, threshold, or timeframe, the retrieved Q&A must either specify that value directly or be a necessary input to computing it. A Q&A that mentions the topic area but gives no numerical guidance is marginally relevant at best.

4. **Temporal currency** — EMA guidance is versioned. Prefer Q&As from the same version context as the query. A Q&A about superseded guidance is relevant only if the query explicitly asks about that version.

## Non-relevant patterns (even when keywords overlap)

- Same keywords, different procedural step: "What is required at step X?" vs. retrieved Q&A answering step Y of the same process.
- Wrong scope: question is about biologicals; retrieved Q&A is about small molecules using identical terminology.
- Definitional vs. operational: question asks how to calculate something; retrieved Q&A only defines the term.
- Adjacent topic: question asks about nitrosamine limits in a specific product; retrieved Q&A discusses nitrosamine testing methods generally without specifying limits.
- Parent-question confusion: EMA Q&A documents have header questions and sub-questions. A header "What are the requirements for X?" without specific guidance is not relevant if a sub-question would give the actual requirement.

## Scoring instruction

Score the retrieved Q&A on a 0–2 scale:
- **2 (relevant)**: Directly and specifically addresses what the query asks; a human expert would use this passage to answer the question.
- **1 (marginal)**: Related to the query topic but missing scope match, specificity, or procedural alignment; might be useful as secondary context.
- **0 (not relevant)**: Shares keywords but does not help answer the query; including it would distract or mislead.

When in doubt between 1 and 2, consider: *Would a regulatory expert cite this specific Q&A in a response to the query?* If yes → 2. If they might mention it as background → 1.
