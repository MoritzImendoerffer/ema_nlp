# Examples — steering retrieval, headless

Runnable Jupyter notebooks that drive the pipeline **without the chat UI** — the same
recipe → agent → structured-answer path `app.py` uses, from plain Python. They walk the
full source-category steering stack ([`docs/RETRIEVAL.md`](../RETRIEVAL.md) §7) in order:

| Notebook | Covers | Needs |
|---|---|---|
| [`01_source_categories.ipynb`](01_source_categories.ipynb) | the category vocabulary + classifier, the persisted `:Document.category`, the one-off backfill | Neo4j (classifier cells run offline) |
| [`02_steered_retrieval.ipynb`](02_steered_retrieval.ipynb) | **Option A** per-call filters + per-profile quotas, **Option B** `LINKS_TO` expansion — driven at the retriever level, no LLM | Neo4j + embed model |
| [`03_routing_and_full_agent.ipynb`](03_routing_and_full_agent.ipynb) | **Option C** routing tables, the `ema_search` tool standalone, the full `steered_agent` recipe end-to-end | Neo4j + embed model; `ANTHROPIC_API_KEY` for the agent section only |
| [`04_topic_subgraphs_eval.ipynb`](04_topic_subgraphs_eval.ipynb) | the **topic-subgraphs evaluation**, unpacked: the benchmark questions, the hub walk + `topic_context` tool live, how `run_eval.py` asks/judges, and the reported result tables reproduced from `mlflow.db` | Mongo + Neo4j + embed model (§2); `mlflow.db` with the 2026-07-13 runs (§5); API key only for the optional §3 |

## Prerequisites

```bash
pip install -e ".[dev]" jupyter    # project + a notebook runtime
scripts/start_services.sh          # MongoDB + Neo4j (Docker), health-checked
```

- Credentials in `~/Nextcloud/Datasets/ema_nlp/ema_nlp.env` (`NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`;
  `ANTHROPIC_API_KEY` for notebook 03 §3). On this host the project Neo4j container runs
  on the alt port — `NEO4J_URI=bolt://localhost:7688`; the notebooks' setup cell defaults
  to it if the env file doesn't set one.
- A built graph. The **full** 79,882-doc graph lives on the GPU host; a dev machine with
  the small verify subset runs everything but returns tiny, homogeneous results.
- `:Document.category` backfilled (notebook 01 does this; it is idempotent).
- The embedding model (`BAAI/bge-large-en-v1.5`, ~1.3 GB) downloads on first use; query
  embedding is fine on CPU.

## Running

```bash
jupyter lab docs/examples/    # or: jupyter notebook / VS Code
```

The setup cell in each notebook finds the repo root and `chdir`s to it, so starting
Jupyter from anywhere inside the repo works. Notebooks are checked in **without outputs**
— if you re-run and commit one, clear outputs first (repo convention: no bulky artifacts
in git).
