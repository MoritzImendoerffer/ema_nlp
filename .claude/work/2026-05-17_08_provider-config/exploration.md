# Exploration: Centralized Provider Configuration

**Work unit:** `2026-05-17_08_provider-config`

---

## Current state — what's hardcoded where

### LLM model name (7 locations)
| File | Hardcoded value |
|------|----------------|
| `harness/judge.py:33` | `DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"` |
| `harness/ablations/a3_reranker.py:24` | `_DEFAULT_MODEL = "claude-haiku-4-5-20251001"` |
| `harness/ablations/a4_reranker.py:22` | `_DEFAULT_MODEL = "claude-haiku-4-5-20251001"` |
| `harness/run_eval.py:103,170` | `"claude-haiku-4-5-20251001"` as fallback strings |
| `app.py:36` | `os.getenv("EMA_CLAUDE_MODEL", "claude-haiku-4-5-20251001")` |
| All 8 YAML configs | `model: claude-haiku-4-5-20251001` |

### Anthropic client instantiation (5 locations)
| File | Pattern |
|------|---------|
| `app.py:185` | `anthropic.AsyncAnthropic()` |
| `harness/judge.py` | `anthropic.Anthropic()` |
| `harness/ablations/a3_reranker.py:86` | `anthropic.Anthropic()` |
| `harness/ablations/a4_reranker.py:76` | `anthropic.Anthropic()` |

All pick up `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` from env automatically — this already works. No changes needed for credentials.

### Embedding model (5 locations)
| File | Hardcoded value |
|------|----------------|
| `harness/embed.py:36` | `EMBED_MODEL_NAME = "BAAI/bge-large-en-v1.5"` |
| `harness/embed.py:40-41` | `_configure_embed_model(model_name)` → `HuggingFaceEmbedding` |
| `harness/run_eval.py:80,83` | fallback `"BAAI/bge-large-en-v1.5"`, `HuggingFaceEmbedding` hardcoded |
| `app.py:76` | calls `_configure_embed_model()` (no args → uses default) |
| All 8 YAML configs | `embed_model: BAAI/bge-large-en-v1.5` |

---

## Architecture of the fix

### Single source of truth: `~/.myenvs/ema_nlp.env`

This file already holds all credentials. LLM/embed settings go here too:

```bash
# Already present:
ANTHROPIC_API_KEY=sk-Z7VX3f...
ANTHROPIC_BASE_URL=https://gw.claudeapi.com

# New — provider defaults:
EMA_LLM_MODEL=claude-haiku-4-5-20251001
EMA_EMBED_MODEL=BAAI/bge-large-en-v1.5
EMA_EMBED_PROVIDER=huggingface   # huggingface | openai
```

YAML configs keep their `model` / `embed_model` fields as **per-run overrides** that take precedence over the env defaults.

### New file: `harness/providers.py`

Central factory module. All code that needs a model name or embed model imports from here.

```python
# harness/providers.py

DEFAULT_LLM_MODEL    = os.getenv("EMA_LLM_MODEL",    "claude-haiku-4-5-20251001")
DEFAULT_EMBED_MODEL  = os.getenv("EMA_EMBED_MODEL",   "BAAI/bge-large-en-v1.5")
DEFAULT_EMBED_PROVIDER = os.getenv("EMA_EMBED_PROVIDER", "huggingface")

def configure_embed_model(model_name: str | None = None) -> None:
    """Set LlamaIndex Settings.embed_model. Call once at startup."""
    name = model_name or DEFAULT_EMBED_MODEL
    provider = DEFAULT_EMBED_PROVIDER
    if provider == "huggingface":
        Settings.embed_model = HuggingFaceEmbedding(model_name=name)
    elif provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding
        Settings.embed_model = OpenAIEmbedding(model=name)
    Settings.llm = None  # retrieval-only; no LLM node needed

def get_llm_model(override: str | None = None) -> str:
    """Return the model name to use — override → env default."""
    return override or DEFAULT_LLM_MODEL
```

### What changes in each file

| File | Change |
|------|--------|
| `harness/embed.py` | `_configure_embed_model()` delegates to `providers.configure_embed_model()` |
| `harness/judge.py` | `DEFAULT_JUDGE_MODEL` replaced with `providers.get_llm_model()` |
| `harness/ablations/a3_reranker.py` | `_DEFAULT_MODEL` replaced |
| `harness/ablations/a4_reranker.py` | `_DEFAULT_MODEL` replaced |
| `harness/run_eval.py` | Fallback strings replaced; embed setup uses `providers.configure_embed_model(embed_model_name)` |
| `app.py` | `CLAUDE_MODEL` uses `providers.get_llm_model(os.getenv("EMA_CLAUDE_MODEL"))` |
| YAML configs | No change — already have `model` and `embed_model` as explicit overrides |

### Provider hierarchy (precedence, high → low)

```
1. YAML config field       (per-run override, e.g. ablation_a_a3.yaml: reranker_model)
2. env var EMA_*           (machine default in ~/.myenvs/ema_nlp.env)
3. harness/providers.py constant  (code default, "claude-haiku-4-5-20251001")
```

---

## What this does NOT do

- No OllamaLLM integration in this work unit (can be a follow-up `EMA_EMBED_PROVIDER=ollama` branch)
- No OpenAI LLM provider wiring (the rerankers and judge all call `anthropic.Anthropic()` directly — swapping LLM provider requires a bigger refactor to use LlamaIndex LLM abstractions)
- No change to how credentials flow (`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` already work via env)

---

## Files to touch

- **New:** `harness/providers.py`
- **Modified:** `harness/embed.py`, `harness/judge.py`, `harness/run_eval.py`, `harness/ablations/a3_reranker.py`, `harness/ablations/a4_reranker.py`, `app.py`
- **Docs:** `docs/SETUP.md` (add LLM/embed env vars section)
- **No change:** YAML configs, tests (embed tests inject models directly — not affected)
