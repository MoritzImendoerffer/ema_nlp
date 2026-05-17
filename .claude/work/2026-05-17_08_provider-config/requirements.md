# Requirements: Centralized Provider Configuration

**Work unit:** `2026-05-17_08_provider-config`

---

## Functional requirements

### FR-1 · Single env-file override
All LLM model names and embedding model defaults are readable from `~/.myenvs/ema_nlp.env`. Changing one line in that file changes the default across the whole pipeline (chat UI, rerankers, judge, eval harness).

### FR-2 · Per-run YAML override
YAML run configs can still specify `model:` and `embed_model:` to override the env default for that run only. Required for ablation reproducibility (each config is self-describing).

### FR-3 · Embedding provider switch
`EMA_EMBED_PROVIDER=huggingface` (default, local) or `EMA_EMBED_PROVIDER=openai` selects the embedding backend. Both use the same `embed_model` name field.

### FR-4 · No credential changes
`ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` already propagate via the Anthropic SDK env vars. No change to credential handling.

### FR-5 · Backward compatible
Existing YAML configs, tests, and CLI commands work unchanged. New env vars are optional with sensible defaults identical to current hardcoded values.

---

## Non-functional requirements

- Single new file: `harness/providers.py` (≤ 60 lines)
- No new dependencies for the default (HuggingFace) path
- `openai` embed provider requires `llama-index-embeddings-openai` (optional dep, not added to core deps)
- Ruff + mypy clean

---

## Acceptance criteria

| # | Criterion |
|---|-----------|
| AC-1 | `harness/providers.py` exists; `configure_embed_model()` and `get_llm_model()` exported |
| AC-2 | `EMA_LLM_MODEL=claude-sonnet-4-6 chainlit run app.py` uses sonnet without any code change |
| AC-3 | `EMA_EMBED_MODEL=BAAI/bge-small-en-v1.5 python -m harness.run_eval --config ...` uses the small model |
| AC-4 | `EMA_EMBED_PROVIDER=openai EMA_EMBED_MODEL=text-embedding-3-small` falls through to `OpenAIEmbedding` |
| AC-5 | All existing tests still pass (embed tests inject model directly — not affected) |
| AC-6 | `docs/SETUP.md` documents the new env vars |
