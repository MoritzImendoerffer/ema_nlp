# Trajectory Step Labeling Rubric — B3 Process Rewards

Use this rubric to label each step in a B1 agent trajectory. Each step consists of:
- **thought**: the agent's internal reasoning
- **action**: the tool called with arguments
- **observation**: the tool's return value

## Labels

### `good_step`
The agent made the right call given the question and what it had already observed.

Criteria (any of these qualifies):
- Called `search()` with query terms directly relevant to the question
- Called `follow_cross_refs()` on a qa_id that the observation explicitly mentioned as related
- Called `filter_by_topic()` with a correct topic keyword that narrows results without losing gold items
- Called `answer()` after gathering all necessary evidence, citing the correct qa_ids
- Changed search strategy (different query) after an unhelpful first search

### `suboptimal_step`
The action is not wrong but wastes effort or misses a more efficient path.

Criteria (any of these qualifies):
- Called `search()` with a generic query when a more specific one was available from context
- Called `follow_cross_refs()` on a qa_id that showed no relevant signal in the observation
- Called `filter_by_topic()` with a keyword that may drop relevant results
- Repeated a search with nearly identical query
- Called `answer()` with missing or incomplete citations (answer text correct but citations wrong)
- Included unnecessary caveats or uncertainty in thought when the observation was clear

### `wrong_step`
The action is incorrect or harmful.

Criteria (any of these qualifies):
- Called `answer()` before gathering enough evidence (answer is wrong or incomplete)
- Called `search()` with a query unrelated to the question (hallucinated direction)
- Called `follow_cross_refs()` on a qa_id that does not exist in the observation
- Ignored a gold qa_id that appeared in the observation
- Misidentified the relevant regulatory procedure (e.g., answered Article 31 question using Article 30 documents)

---

## Format

Each label is one JSONL line in `trajectory_labels.jsonl`:

```json
{
  "bench_id": "T3-001",
  "step": 1,
  "thought": "...",
  "action": "search(...)",
  "observation_summary": "5 results, top qa_id=abc123",
  "label": "good_step",
  "reason": "correct query targeting the Type IB/II timetable combination"
}
```

**Reason must be one line.** Focus on *why* the step is labeled this way, not what it does.

---

## Calibration check

Label the first 10 steps, then re-read your labels before continuing:
- Are all `good_step` labels clearly justified by the rubric?
- Are you labeling `suboptimal_step` too strictly (expecting the agent to be perfect)?
- If you labeled the same action differently in two similar questions, reconcile.

Aim for ~50+ labeled steps. At <30, the signal is too sparse for few-shot learning.
