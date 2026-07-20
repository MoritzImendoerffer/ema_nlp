# `corrective_search` — CRAG as a tool

`harness/tools/corrective_search.py` (loop) + `harness/retrieval/corrective.py`
(pure primitives). Corrective RAG: retrieve, **grade** the passages against the
question, **rewrite** the query for what is missing, retry — bounded, keeping the
best attempt.

This is the project's stance on RAG techniques: CRAG is a *tool*, not a separate
engine. A recipe that lists `corrective_search` is a CRAG system.

## Signature

```python
corrective_search(query: str) -> str
```

One argument. The correction loop is internal — the agent does not steer it.

## What the LLM reads

> Corrective retrieval over the EMA human-regulatory corpus: searches, grades
> passage relevance, and rewrites + retries the query (bounded) when the passages
> don't fully cover the question. Returns corrected passages.

## The loop

```
nodes ← retrieve(q)
grade ← grader_llm(question, nodes)          # per-doc scores + missing facts
best  ← (nodes, grade)
while not sufficient(grade) and cycles < MAX_CYCLES:   # MAX_CYCLES = 2
    q     ← grader_llm.rewrite(q, missing)
    nodes ← retrieve(q)
    grade ← grader_llm(question, nodes)
    if grade ≥ best.grade: best ← (nodes, grade)       # ties prefer the later cycle
return format(best.nodes) + grade_note
```

- **Sufficient** = at least one score-2 (fully relevant) document **and** no
  missing facts.
- **Best-so-far** matters: a rewrite can retrieve *worse* than an earlier attempt,
  so the loop returns the highest-graded retrieval rather than the last one.
- **Bounded**: at most 2 rewrite cycles, so worst case is 3 retrievals + 3 grades.

## The grader model

Grading and rewriting use a **cheap, separately configured** model
(`grader_role`, default `grader` in `harness/configs/models.yaml`) — deliberately
*not* the agent's model. The agent never passes its own LLM in production. This
keeps the correction loop's cost roughly independent of the answer model tier.

## Output format

`format_nodes(...)` output (identical to [`ema_search`](ema_search.md), including
`via=` and `path=` tags) followed by a grade note:

```
[corrective: 1 rewrite cycle, 2 relevant / 1 partial, missing: fee amounts]
```

The note is also recorded as a chain-step note, and when the query changed a
second note records the final rewritten query verbatim — so the chain HTML shows
*how* the question was reformulated.

## Configuration

```yaml
orchestration:
  tools: [corrective_search, ema_search]   # recipe: crag_agentic
```

Builder knobs (rarely overridden): `grader_role`, `max_cycles`, plus the shared
`transform` / `postprocessors` pipeline. The retrieval quality itself comes from
the index profile — see [`retriever.md`](retriever.md).

## Observability

Feeds the shared node sink (citations + judges see the corrected passages, not
the discarded attempts) and records one `ChainStep` per call carrying the grade
note and the rewritten query.

## Failure modes

- **Grader returns unparseable output** → `parse_grade` degrades to "not
  sufficient"; the loop still terminates on the cycle bound.
- **All cycles poor** → returns the best attempt anyway, with the grade note
  stating what is still missing. It never returns nothing silently.
- **Cost** — up to 3× the retrievals plus grader calls; use `crag_agentic` when
  the question type justifies it, not by default.

## Tests

`tests/test_tools_corrective.py` — grading, rewriting, the cycle bound,
best-so-far selection (including the tie rule), and sink behavior. The pure
primitives are unit-tested independently of any LLM.
