# README outline — `ema-rag-benchmark`

*This is a v1 outline, not the final README. Fill in code-level details once Phase 3 harness exists.*

---

## Title line
**EMA-RAG-Benchmark** — A Q&A benchmark for retrieval-augmented generation over European Medicines Agency regulatory content.

## Badges row (when ready)
License · Python version · Last update · arXiv preprint · DOI (Zenodo)

## One-paragraph pitch
> There is no public benchmark for RAG on European Medicines Agency content. Existing pharmaceutical-regulatory RAG work is FDA/ICH-only; existing biomedical RAG benchmarks (MIRAGE, PubMedQA, MedQA) test clinical and literature knowledge, not regulatory industry knowledge. This project fills that gap with a Q&A benchmark mined from expert-authored EMA Q&A documents, plus reference RAG implementations and three targeted ablations that probe where subject-matter-expert effort actually improves retrieval.

## What's in this repo
- **Corpus** — ~200+ Q&A pairs extracted from EMA HTML accordion pages and Q&A PDFs, normalized to one schema with topic and version metadata.
- **Benchmark** — 30–50 stratified evaluation questions across four types (Lookup / Scoping / Multi-hop / Synthesis), each with gold answers and gold source Q&As.
- **Harness** — five-metric evaluation pipeline (Recall@k, Precision@k, Faithfulness, Correctness, Citation Accuracy), MIRAGE-style.
- **Ablations** — three pre-registered experiments testing SME interventions at retrieval, agent-planning, and prompting layers.

## Quickstart

```bash
pip install -e ".[dev]"
scripts/start_services.sh                     # MongoDB + Neo4j
ls harness/configs/recipes/                   # available RAG / agent recipes
python scripts/run_eval.py --recipe naive_rag # recipe × benchmark → per-type MLflow runs
bash run_ui.sh                                # Chainlit chat UI (MLflow tracing)
```

## Why this benchmark exists

**Gap.** Every major biomedical RAG benchmark evaluates clinical evidence or exam knowledge, not regulatory industry knowledge. The only open pharma-regulatory RAG work (QA-RAG, Jaymax FDA FAQ) is US-only.

**Source choice.** EMA publishes *expert-authored Q&A documents* — regulatory writers pre-build question-answer pairs over the same corpus a RAG system would retrieve from. This is an almost-free ground truth.

**Scope lock.** Human-regulatory only. English only. Accordion-HTML and PDF Q&As only.

## The benchmark

### Corpus schema
*(expand from ROADMAP Phase 1.1)*

### Question-type taxonomy
| Type | What it tests | % of benchmark |
|---|---|---|
| T1 Lookup | Single-Q single-source retrieval | ~40% |
| T2 Scoping | Topically adjacent disambiguation | ~20% |
| T3 Multi-hop | `cross_refs` traversal | ~20% |
| T4 Synthesis | Cross-document recall | ~20% |

### Metrics
*(expand from ROADMAP Phase 3.2)*

## Ablations

Each ablation is one config flag flip against the baseline. Pre-registered expected directions:

| Ablation | Expected effect | Prior-art anchor |
|---|---|---|
| A — Evidence filtering + query reformulation | Largest on T2 and T3 | Bosko et al. +12/+8.2; MIRAGE ±18 |
| B — Process-reward supervision | Largest on T3 and T4 | RAG-Gym +19 F1 |
| C — SME few-shot across model tiers | Shrinks on frontier reasoning models | Medprompt → o1 |

Results are reported per question type, not just aggregate. The interesting finding is *which types break for which interventions*.

## Limitations (read this before using)
- Small benchmark (30–50 items) — detects large effects only. Bootstrap CIs reported.
- English only. No multilingual.
- EU regulatory only. Not transferable to FDA/ICH/PMDA as-is.
- Q&As are pre-authored by EMA experts — this makes gold cheap but may underrepresent questions regulators *would want to ask but haven't*.
- LLM-as-judge metrics (Faithfulness, Correctness) are validated against a 20% hand-graded sample; residual judge noise remains.
- Not a clinical benchmark. Do not use for clinical decision support.

## How to contribute
- Add a new ablation: express it as a recipe/config under `harness/configs/` (see `docs/RECIPES.md` for the contract).
- Propose additional question types: open an issue with the test hypothesis.
- Translate the benchmark: multilingual extension is planned for v2; early collaborators welcome.

## Citation
```
@misc{ema_rag_benchmark_2026,
  title  = {EMA-RAG-Benchmark: A Q&A benchmark for retrieval-augmented generation over European Medicines Agency content},
  author = {...},
  year   = {2026},
  url    = {...}
}
```

If you use this benchmark, please also cite the underlying EMA source documents (reference numbers are in `corpus.jsonl`).

## License
- Code: MIT
- Benchmark data: CC-BY-4.0 (derived from EMA content, reproducible with source attribution per EMA's terms)

## Acknowledgements
- Methodology inspired by MIRAGE/MedRAG (Xiong et al., ACL 2024), RAG-Gym (Xiong et al., 2025), and Self-RAG (Asai et al., ICLR 2024).
- Source content: © European Medicines Agency; reproduction authorized with source acknowledgement.
