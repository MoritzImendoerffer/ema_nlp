# `resolve_substance` — substance name → canonical identity

`harness/tools/substance.py`. The only tool that leaves the corpus: resolves a
drug or chemical name against **PubChem** to get CAS number, synonyms and
molecular weight.

## Signature

```python
resolve_substance(substance_name: str) -> dict   # a Substance model dump
```

## What the LLM reads

> Resolve a drug or chemical substance name to its canonical identity (CAS
> number, synonyms, molecular weight) using PubChem. Use this to disambiguate
> substances and acronyms before searching the corpus.

## Why it exists

EMA documents refer to the same substance many ways — INN, brand name, salt
form, abbreviation, or an impurity code. Resolving first gives the agent
**synonyms to search with**, which matters in a corpus where the wrong name
simply returns nothing.

It is also part of the project's acronym defence. In EMA Q&A documents
**"AI" means Acceptable Intake** (a toxicology limit in ng/day), not artificial
intelligence — see `project_roadmap/GLOSSARY.md`. Substance resolution plus the
acronym transform (`harness/configs/retrieval/acronyms.yaml`) keep that
disambiguation explicit rather than hoping the model guesses right.

## Configuration

```yaml
orchestration:
  tools: [ema_search, resolve_substance]
```

No config of its own. The builder accepts a `fetcher` override, which is how
tests inject a fake HTTP client — production passes none.

## Output

A `Substance` model dump: canonical name, CAS, synonym list, molecular weight,
and whether resolution succeeded. Unresolvable names come back as an explicit
"not found" result rather than an exception, so the agent can proceed with the
literal term.

## Failure modes

- **Network unavailable / PubChem down** → returns an unresolved result; the run
  continues. Nothing else in the pipeline depends on it.
- **Ambiguous name** → PubChem's own best match; the synonym list is what the
  agent should use for a follow-up search.
- **Not a chemical** (a procedure name, a committee) → unresolved, as expected.

## Not in the chain view

This tool is not retrieval-shaped: it returns no passages, so it does not feed
the node sink and does not appear in the retrieval-chain export. It does appear
in the MLflow trace as a tool span.

## Tests

`tests/test_tools.py` (registry) and the substance tests with a fake fetcher —
no live network in the offline suite.
