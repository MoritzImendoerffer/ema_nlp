# Claude Code setup guide for `ema-rag-benchmark`

*A practical guide: install Claude Code, configure it well for this specific project, and work with it effectively across the roadmap phases.*

---

## What Claude Code is, briefly

Claude Code is a command-line agent that lives in your terminal, reads and writes files in your repo, and can run shell commands. Unlike this chat, it has persistent access to your actual filesystem and can iterate in tight loops (edit → test → re-edit). It is the right tool once you have a concrete file structure and want to build.

- Docs: https://docs.claude.com/en/docs/claude-code/overview
- npm package: https://www.npmjs.com/package/@anthropic-ai/claude-code

Note that the Claude Code docs change often — check the official docs above if any command in this guide behaves unexpectedly.

---

## Part 1 — Installation

### Prerequisites
- Node.js 18+ (install from https://nodejs.org if you don't have it; verify with `node --version`)
- Git
- A Claude account — you'll authenticate through your Claude subscription or an Anthropic API key

### Install on Linux / macOS
```bash
npm install -g @anthropic-ai/claude-code
```

### Install on Windows
Either WSL (recommended — treat as Linux) or native PowerShell:
```powershell
npm install -g @anthropic-ai/claude-code
```

### Verify
```bash
claude --version
```

### Authenticate
On first run, Claude Code will prompt for authentication. You can use a Claude subscription (OAuth login) or an Anthropic API key. Subscription is typically cheaper for sustained use; API keys work fine for occasional use or for CI.

### Diagnose if something breaks
```bash
/doctor     # inside a Claude Code session — reports install/auth/config issues
```

---

## Part 2 — Set up the project repo

### Recommended structure (from the roadmap)
```
ema-rag-benchmark/
├── CLAUDE.md                 ← the most important file in this guide
├── README.md
├── pyproject.toml            ← or requirements.txt
├── .gitignore
├── corpus/
│   ├── corpus.jsonl
│   ├── SCHEMA.md
│   └── extraction/
│       ├── html_accordion.py
│       └── pdf_qa.py
├── benchmark/
│   ├── benchmark.jsonl
│   ├── TAXONOMY.md
│   └── curation_notes.md
├── harness/
│   ├── run_eval.py
│   ├── judges/
│   └── configs/
├── ablations/
│   ├── A_evidence_filter/
│   ├── B_process_rewards/
│   └── C_prompting_matrix/
├── results/
├── docs/
│   ├── ROADMAP.md            ← the one I wrote
│   ├── GLOSSARY.md           ← the one I wrote
│   └── methodology.md
└── tests/
```

### Initialize
```bash
mkdir ema-rag-benchmark && cd ema-rag-benchmark
git init
python -m venv .venv && source .venv/bin/activate  # or your preferred env manager
```

Copy the ROADMAP.md and GLOSSARY.md from this conversation into `docs/`. These become reference material for Claude Code.

---

## Part 3 — Writing a good CLAUDE.md

**This is the single highest-leverage thing you'll do.** Claude Code reads `CLAUDE.md` from your project root at the start of every session. It becomes part of the system prompt, so it's always loaded.

### The principles that matter

1. **Less is more.** Research suggests frontier LLMs can follow ~150–200 instructions reliably, and Claude Code's own system prompt already uses ~50. Every instruction you add competes for attention. Keep CLAUDE.md to ~100–200 lines for this project.
2. **WHAT, WHY, HOW.** What the project is (tech stack, structure), why it exists (goal), how to work on it (commands, conventions).
3. **Progressive disclosure.** Don't inline everything. Point to detailed docs (ROADMAP.md, GLOSSARY.md) so Claude can read them when needed, rather than bloating the always-loaded context.
4. **Write it by hand, don't auto-generate.** `/init` is a starting point, but the highest-leverage CLAUDE.md comes from you thinking about friction points.

### A starter CLAUDE.md for this project

Save this as `CLAUDE.md` at the repo root:

```markdown
# EMA-RAG-Benchmark

## What this project is
A Q&A benchmark and reference RAG implementations built from European Medicines Agency (EMA) human-regulatory content. Three deliverables:
- `corpus/corpus.jsonl` — normalized Q&A pairs mined from EMA HTML and PDF sources
- `benchmark/benchmark.jsonl` — ~30–50 stratified evaluation questions with gold answers
- `harness/` — MIRAGE-style evaluation pipeline

## Why
No public Q&A benchmark exists for EMA regulatory content. See `docs/ROADMAP.md` for the full project plan and motivation. See `docs/GLOSSARY.md` for regulatory and NLP terminology — refer to it whenever you encounter unfamiliar pharma terms.

## Project phase
We are currently in **Phase X** (update this line as we progress). Phase definitions are in `docs/ROADMAP.md`. Do not introduce work from later phases without asking.

## Tech stack
- Python 3.11+
- Data: pandas, jsonlines
- Parsing: BeautifulSoup4, PyMuPDF, pymupdf4llm
- Embeddings/retrieval: sentence-transformers (BGE-large, local CUDA) + LlamaIndex over **Neo4j** `PropertyGraphIndex` (no qdrant/FAISS doc store — FAISS survives only as the semantic query cache)
- LLM clients: anthropic, openai
- Testing: pytest
- Linting + formatting: ruff (`ruff check` / `ruff format`)

## Commands
- Install deps: `pip install -e ".[dev]"`
- Run tests: `pytest`
- Lint: `ruff check .`
- Format: `ruff format .`
- List recipes / launch UI: `ls harness/configs/recipes/` · `bash run_ui.sh` · eval: `python scripts/run_eval.py --recipe <name>`

## Conventions
- All data files are JSONL, one record per line
- Schema changes require updating both `corpus/SCHEMA.md` and the corresponding dataclass
- LLM prompts live in files, not as string literals in code — makes them diffable
- Every ablation config gets its own YAML under `harness/configs/`
- Results are recorded as MLflow runs (the system of record); the resolved config is stamped on every run/trace
- Never commit anything under `data/raw/` — those are large scraped artifacts

## Important constraints (read before making changes)
- Scope lock: EMA human-regulatory content only — no clinical-trial documents, no FDA content. *(EPARs are now **in scope for retrieval** since 2026-06-02 — ~18k EPAR reports are indexed into Neo4j. Benchmark Q&A curation scope is unchanged. The earlier "no EPARs" lock is lifted for retrieval.)*
- Neo4j is the **live retrieval store** (a hierarchical `PropertyGraphIndex`); a typed-ontology seam exists under `harness/ontology/`. *(The earlier "no ontology/graph infrastructure in v1" lock is superseded — see `ROADMAP.md` and `DECISIONS.md`.)*
- When unsure whether a task fits v1 scope, ask before implementing.

## Working style
- Prefer small, reviewable changes
- Write the test first when adding a new function
- Keep pure-Python data-processing logic separate from I/O and LLM calls — makes testing easy
- When adding a new dependency, note in the PR why it's needed
```

### Things I deliberately left out of this CLAUDE.md

- Long prose descriptions (they waste tokens)
- The full roadmap (it's in `docs/ROADMAP.md`; the file points to it)
- Regulatory definitions (they're in `docs/GLOSSARY.md`; the file points to it)
- Coding style micro-rules (let `ruff` and `black` enforce them via config)

As you hit friction points, add to CLAUDE.md. Each added rule should solve a real problem you encountered, not a theoretical concern.

### Optional: `CLAUDE.local.md`
If you want project instructions that are personal to you and shouldn't be shared (e.g., local paths, your preferred verbosity), put them in `CLAUDE.local.md` and add it to `.gitignore`. Claude Code loads it if present.

---

## Part 4 — Effective working patterns

The workflow patterns below are what make Claude Code feel productive versus frustrating.

### Pattern 1 — Interview-driven specs for new phases
Before starting each roadmap phase, open a Claude Code session and use the interview pattern:

> I want to build [Phase 1 of the roadmap — corpus extraction]. Read docs/ROADMAP.md and CLAUDE.md first. Then interview me in detail using the AskUserQuestion tool. Ask about technical implementation, edge cases, and tradeoffs. Don't ask obvious questions — dig into the hard parts I might not have considered. Keep interviewing until we've covered everything, then write a complete spec to docs/specs/phase1.md.

Then start a **fresh session** to execute the spec. Fresh context + written spec beats a single mega-session that drifts.

### Pattern 2 — Plan mode before code
Use `/model` to select an Opus-tier model for planning (or enable Plan mode if available in your version). Have Claude produce a plan *file* before writing code. Review the plan. Correct it. *Then* let Claude implement.

This is especially valuable for phases 3–4 where mistakes compound (a wrong eval harness gives wrong results for every ablation).

### Pattern 3 — Tight feedback loops
The single highest-value habit: **interrupt Claude early when it goes off track.** Press `Esc` to stop mid-action. Correct. Restart. Don't let a wrong trajectory compound for ten minutes.

Corollary: if Claude produces something mediocre, don't keep patching it. Try:
> Knowing everything you know now, scrap this and implement the elegant solution.

### Pattern 4 — Let Claude challenge you
After implementing something, before committing:
> Grill me on these changes. Find bugs. Argue with me about design choices you disagree with.

Or on tests:
> Prove to me this implementation is correct. Add the missing edge-case tests that would catch a regression.

This surfaces issues earlier than review does.

### Pattern 5 — Phase-gated, test-gated plans
For each phase of the roadmap, make Claude produce a phase-wise gated plan with tests at each gate. Don't let it blow through phases. Example structure of a phase plan:

1. **Gate A:** PDF extractor produces records for one known document (nitrosamine Q&A). Test: record count matches expected 22 questions.
2. **Gate B:** Extractor handles the full PDF corpus. Test: all records validate against schema.
3. **Gate C:** Cross-references are extracted. Test: specific known Q22→Q20→Q10 chain is present.

Each gate has a test that must pass before proceeding.

### Pattern 6 — Use a second Claude session for review
Start a separate Claude Code session and say:
> Review the changes in the last commit as a staff engineer. What's wrong, what's missing, what would you do differently?

The review-session Claude won't be attached to the implementation Claude's choices, and tends to find real issues.

### Pattern 7 — Explore, then execute
In a new codebase area, let Claude explore first:
> Read the corpus/extraction/ directory and summarize the current approach. Don't write code yet.

Then plan, then execute. Don't let Claude start editing before it understands the terrain.

---

## Part 5 — Project-specific tips

### Handling EMA's heterogeneous Q&A formats
The corpus has three layouts (HTML accordions, Q&A PDFs with numbered sections, landing pages to filter out). Use Claude Code to build *one parser per layout* in a branch, then merge. Don't try a single "universal" parser — it will have more edge cases than code.

### Working with regulatory terminology
Keep `docs/GLOSSARY.md` updated as you discover new terms. Reference it explicitly when asking Claude to work on pharma-specific code:
> When you encounter unfamiliar regulatory acronyms, check docs/GLOSSARY.md before guessing.

The "AI" name collision (Acceptable Intake vs Artificial Intelligence) is a real bug source — the glossary flags it.

### Benchmark curation
When you get to Phase 2, do *not* let Claude generate benchmark questions unsupervised. The SME review (you) is what makes the benchmark credible. A good workflow:
1. Claude proposes candidate questions from corpus records
2. You accept / reject / edit each one
3. Claude formalizes accepted items into the benchmark schema

### LLM-judge cost management
Phase 3 and 4 run a lot of LLM-judge calls. Track spend:
- Use cheaper models (e.g., Haiku-tier) for noisy bulk judging with a more expensive model for spot-checking
- Cache results — rerunning the same eval shouldn't call the API again
- Hand-grade a 20% sample to calibrate judge reliability

### Git hygiene
- Commit corpus/benchmark data changes in separate commits from code changes
- Never commit large raw data (your existing `data/raw/`) — add to `.gitignore`
- Use branches per roadmap phase; merge only when the phase's success criteria are met

### MCPs worth connecting (optional, later)
Once you've done a pass through the roadmap, consider adding MCP servers:
- `ema-mcp` (https://github.com/openpharma-org/ema-mcp) — if you ever extend to EPAR or product data
- GitHub MCP — for issue/PR work if you open-source the repo

MCPs add tool surface that Claude Code can use directly. Don't add them upfront; add when you have a need.

---

## Part 6 — Anti-patterns (things not to do)

- **Do not auto-generate CLAUDE.md with `/init` and leave it.** The whole value is in your hand-written, friction-informed guidance. Use `/init` as a starting point only.
- **Do not inline the full roadmap or glossary into CLAUDE.md.** Keep CLAUDE.md short. Link to the long docs.
- **Do not let Claude build the eval harness before you've written the config spec.** A wrong harness produces wrong numbers on every ablation. Spec first.
- **Do not treat LLM-judge scores as ground truth.** Calibrate against hand grades.
- **Do not commit secrets or API keys.** Use `.env` + `.gitignore`.
- **Do not run long unattended sessions.** Tight feedback loops beat one big session.
- **Do not add ontology/graph infrastructure "just in case."** It's in the deferral list for a reason.

---

## Part 7 — Useful commands reference

Inside a Claude Code session:

| Command | What it does |
|---|---|
| `/init` | Generate a starter CLAUDE.md (edit after) |
| `/model` | Switch model or reasoning level |
| `/context` | Show context-window usage |
| `/doctor` | Diagnose install/auth/config problems |
| `/config` | Open configuration |
| `/compact` | Compact context when hitting limits |
| `/usage` | Check plan limits |
| `Esc` | Stop Claude mid-action |

---

## Part 8 — Suggested first session

When everything is installed and `CLAUDE.md` is in place, open a session in the repo root and try:

> I've just set up this repo. Read `CLAUDE.md`, `docs/ROADMAP.md`, and `docs/GLOSSARY.md`. Then tell me back in your own words: (1) what Phase 0 requires, (2) what files or data are expected to exist but don't yet, (3) what clarifying questions you have before we start Phase 0.

This confirms Claude Code loaded the context correctly and flushes out gaps before you start.

---

## References
- Claude Code overview: https://docs.claude.com/en/docs/claude-code/overview
- Claude Code best practices: https://code.claude.com/docs/en/best-practices
- CLAUDE.md guide (Anthropic): https://claude.com/blog/using-claude-md-files
- CLAUDE.md design essay (HumanLayer): https://www.humanlayer.dev/blog/writing-a-good-claude-md
- Community best-practices repo: https://github.com/shanraisshan/claude-code-best-practice
