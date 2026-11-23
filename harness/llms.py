"""
LlamaIndex LLM factory — role-based model selection.

Reads model configuration from harness/configs/models.yaml via
harness.models.load_model_for_role(). Returns a LlamaIndex LLM instance
compatible with llm.chat(), llm.achat(), and all LlamaIndex workflows.

Usage::

    from harness.llms import get_llm

    llm = get_llm("agent")    # → Anthropic(claude-haiku-4-5, ...)
    llm = get_llm("judge")    # → Anthropic(claude-opus-4-7, ...)
    llm = get_llm("grader")   # → Anthropic(claude-haiku-4-5, ...) by default

Available roles (defined in models.yaml):
    agent, grader, rewriter, reranker, judge, reviewer
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from llama_index.core.llms import LLM

from harness.models import load_model_for_role

log = logging.getLogger(__name__)

_TOGETHER_BASE_URL = "https://api.together.xyz/v1"


def get_llm(role_name: str) -> LLM:
    """
    Return a LlamaIndex LLM for the given role.

    Args:
        role_name: Role key defined in models.yaml (e.g. 'agent', 'judge').

    Returns:
        Anthropic LLM for anthropic provider,
        OpenAI (Together AI) for together_ai provider,
        OpenAI (custom api_base) for openai_compatible provider.

    Raises:
        EnvironmentError: If the required API key env var is missing.
        ValueError:       If the role or provider is unrecognised.
    """
    cfg = load_model_for_role(role_name)

    if cfg.provider == "anthropic":
        return _make_anthropic(cfg.model_id, cfg.temperature, cfg.max_tokens)
    elif cfg.provider == "together_ai":
        return _make_together(cfg.model_id, cfg.temperature, cfg.max_tokens)
    elif cfg.provider == "openai_compatible":
        return _make_openai_compatible(
            cfg.model_id, cfg.temperature, cfg.max_tokens,
            api_base=cfg.api_base or "http://localhost:8000/v1",
            api_key_env=cfg.api_key_env or "OPENAI_API_KEY",
        )
    else:
        raise ValueError(
            f"Unknown provider '{cfg.provider}' for role '{role_name}'. "
            "Expected 'anthropic', 'together_ai', or 'openai_compatible'."
        )


def get_llm_for_model(model_name: str, temperature_override: float | None = None) -> LLM:
    """Build a LlamaIndex LLM from a model name key in models.yaml.

    Useful when the caller knows the model name directly rather than a role.

    Args:
        model_name:          Key in the models: section of models.yaml.
        temperature_override: Replaces the temperature from models.yaml if given.

    Raises:
        ValueError:      If model_name is not in models.yaml.
        EnvironmentError: If required API key is missing.
    """
    import yaml

    models_yaml = Path(__file__).parent / "configs" / "models.yaml"
    with models_yaml.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    models: dict = raw.get("models", {})
    if model_name not in models:
        raise ValueError(f"Unknown model '{model_name}'. Available: {sorted(models)}")

    d = models[model_name]
    temp = temperature_override if temperature_override is not None else float(d["temperature"])
    model_id = d["model_id"]
    max_tokens = int(d["max_tokens"])
    provider = d["provider"]

    if provider == "anthropic":
        return _make_anthropic(model_id, temp, max_tokens)
    elif provider == "together_ai":
        return _make_together(model_id, temp, max_tokens)
    elif provider == "openai_compatible":
        return _make_openai_compatible(
            model_id, temp, max_tokens,
            api_base=d.get("api_base", "http://localhost:8000/v1"),
            api_key_env=d.get("api_key_env", "OPENAI_API_KEY"),
        )
    raise ValueError(f"Unknown provider '{provider}' for model '{model_name}'.")


# Model-id prefixes the Anthropic API rejects `temperature` for (HTTP 400
# "`temperature` is deprecated for this model" — the Claude 5 family). The
# installed llama-index ANTHROPIC_NO_TEMP_MODELS list covers only opus-4-7/4-8,
# so the wrapper strips it for these too. Prefix match (not substring): a
# substring "-5" would wrongly hit claude-haiku-4-5. claude-opus-5 was added on
# 2026-11-23: a real call with claude-opus-5-5 returned that 400, and the inline
# judge (harness/judge.py, roles.judge) swallows the error and logs a warning only.
_NO_TEMPERATURE_PREFIXES = ("claude-sonnet-5", "claude-opus-5", "claude-fable-5", "claude-mythos-5")


_ANTHROPIC_MODELS_WARMED = False


def warm_anthropic_models() -> int:
    """Build the serializers of the anthropic SDK's response models, once per process.

    The SDK builds a response with ``construct_type``, without validation, so a model class
    with ``defer_build`` keeps a ``MockValSer`` placeholder until something calls
    ``model_dump`` on one of its objects directly. mlflow's LlamaIndex autolog closes the
    ``CHAT_MODEL`` span of ``Anthropic.achat`` before :meth:`_Anthropic._sanitize` runs, and
    serializes the raw response with its JSON encoder: "'MockValSer' object is not an
    instance of 'SchemaSerializer'". The span never ends, and the trace is written late.

    Seen on 2026-11-23 in the first item of a live evaluation run with ``claude-opus-4-7``
    (``ToolUseBlock``, ``DirectCaller``, ``CacheCreation`` and ``OutputTokensDetails`` were
    unbuilt); a ``claude-haiku-4-5`` response did not fail. Only the first such response of
    a process failed, because the sanitize step then builds the classes.

    Returns the number of classes built; 0 after the first call.
    """
    global _ANTHROPIC_MODELS_WARMED
    if _ANTHROPIC_MODELS_WARMED:
        return 0
    import anthropic.types  # noqa: F401  (imports the response-model modules)
    from pydantic import BaseModel

    built = 0
    for name, module in list(sys.modules.items()):
        if not name.startswith("anthropic.types") or module is None:
            continue
        for obj in list(vars(module).values()):
            if not (isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == name):
                continue
            serializer = type(obj.__dict__.get("__pydantic_serializer__")).__name__
            if obj.__pydantic_complete__ and serializer != "MockValSer":
                continue
            try:
                obj.model_rebuild(force=True)
                built += 1
            except Exception as exc:  # a class that cannot build stays as it is
                log.debug("could not build %s.%s: %s", name, obj.__name__, exc)
    _ANTHROPIC_MODELS_WARMED = True
    return built


def _make_anthropic(model_id: str, temperature: float, max_tokens: int) -> LLM:
    try:
        from llama_index.llms.anthropic import Anthropic
    except ImportError as exc:
        raise ImportError("pip install llama-index-llms-anthropic") from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError("ANTHROPIC_API_KEY not set. Add it to ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env")

    # Before the first traced call: an unbuilt SDK class makes autolog's span fail to end.
    warm_anthropic_models()

    class _Anthropic(Anthropic):
        """Anthropic wrapper hardened against two library bugs (GPU walk 2026-07-07).

        1. llama-index's structured-output path (``generate_structured_response`` →
           ``FunctionCallingProgram``) forwards ``tool_choice=None`` through kwargs,
           which OVERRIDES the wrapper's correctly-built tool_choice object and sends
           ``"tool_choice": null`` to the API → HTTP 400 "tool_choice: Input should
           be an object" (llama-index-core 0.14.22). Dropping the explicit ``None``
           restores the wrapper's own mapping; a real dict passes through untouched.
        2. ``AnthropicChatResponse.raw`` holds live anthropic-SDK pydantic objects
           whose classes are built lazily (``defer_build``); under pydantic 2.13 the
           parent's recursive serializer bakes in a ``MockValSer`` for them, so any
           attempt to ``model_dump()`` the response — which MLflow autolog does when
           closing every LLM span — raises "'MockValSer' object is not an instance
           of 'SchemaSerializer'", the span never ends, and ``mlflow.genai.evaluate``
           loses the row's trace (``eval_item.trace is None`` crash). Converting
           ``raw`` to plain JSON-able data right after each call makes responses
           serialization-safe; per-object ``model_dump()`` works fine individually.

        Plus two API-evolution shims for the Claude 5 family (2026-07-13),
        which the installed library's static model tables predate:

        3. Claude 5 models deprecate the ``temperature`` request field (400 on
           any value); ``_model_kwargs`` drops it for
           :data:`_NO_TEMPERATURE_PREFIXES` matches.
        4. ``metadata`` falls back to correct Claude-5 values when the
           library's ``anthropic_modelname_to_contextsize`` raises "Unknown
           model" — without this the agent path dies on the lookup, and the
           library's ``is_function_calling_model`` ("-3"/"-4" substring check)
           would silently disable tool calling for Claude 5 names.
        """

        @property
        def _model_kwargs(self) -> dict:
            kwargs = super()._model_kwargs
            if str(self.model).startswith(_NO_TEMPERATURE_PREFIXES):
                kwargs.pop("temperature", None)
            return kwargs

        @property
        def metadata(self) -> Any:
            try:
                return super().metadata
            except ValueError:  # model newer than the library's static table
                from llama_index.core.llms import LLMMetadata

                return LLMMetadata(
                    context_window=200_000,  # Claude 5 family context window
                    num_output=self.max_tokens,
                    is_chat_model=True,
                    model_name=self.model,
                    is_function_calling_model=True,
                )

        @staticmethod
        def _plain(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                try:
                    return value.model_dump()
                except Exception:
                    return str(value)
            if isinstance(value, dict):
                return {k: _Anthropic._plain(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_Anthropic._plain(v) for v in value]
            return value

        @classmethod
        def _sanitize(cls, response: Any) -> Any:
            raw = getattr(response, "raw", None)
            if raw is not None and not isinstance(raw, (str, int, float, bool)):
                try:
                    response.raw = cls._plain(raw)
                except Exception:  # never let sanitation break a live call
                    pass
            return response

        def chat(self, *args: Any, **kwargs: Any) -> Any:
            return self._sanitize(super().chat(*args, **kwargs))

        async def achat(self, *args: Any, **kwargs: Any) -> Any:
            return self._sanitize(await super().achat(*args, **kwargs))

        def stream_chat(self, *args: Any, **kwargs: Any) -> Any:
            gen = super().stream_chat(*args, **kwargs)

            def _gen():
                for item in gen:
                    yield self._sanitize(item)

            return _gen()

        async def astream_chat(self, *args: Any, **kwargs: Any) -> Any:
            gen = await super().astream_chat(*args, **kwargs)

            async def _gen():
                async for item in gen:
                    yield self._sanitize(item)

            return _gen()

        # NOTE: the signature must mirror the parent exactly — llama-index probes
        # it (inspect.signature) to decide whether ``tool_required`` is supported;
        # a bare *args/**kwargs override makes it silently drop tool_required.
        def _prepare_chat_with_tools(
            self,
            tools: Any,
            user_msg: Any = None,
            chat_history: Any = None,
            verbose: bool = False,
            allow_parallel_tool_calls: bool = False,
            tool_required: bool = False,
            **kwargs: Any,
        ) -> dict:
            if kwargs.get("tool_choice", ...) is None:
                kwargs.pop("tool_choice")
            return super()._prepare_chat_with_tools(
                tools,
                user_msg=user_msg,
                chat_history=chat_history,
                verbose=verbose,
                allow_parallel_tool_calls=allow_parallel_tool_calls,
                tool_required=tool_required,
                **kwargs,
            )

    from harness.models import anthropic_headers

    return _Anthropic(
        model=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        # The workspace header for an organization-scoped key; None when unset.
        default_headers=anthropic_headers() or None,
    )


def _make_together(model_id: str, temperature: float, max_tokens: int) -> LLM:
    try:
        from llama_index.llms.openai import OpenAI
    except ImportError as exc:
        raise ImportError("pip install llama-index-llms-openai") from exc

    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise OSError(
            "TOGETHER_API_KEY not set. Add it to ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env. "
            "Get a key at https://api.together.xyz"
        )

    return OpenAI(
        model=model_id,
        api_base=_TOGETHER_BASE_URL,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _make_openai_compatible(
    model_id: str,
    temperature: float,
    max_tokens: int,
    *,
    api_base: str,
    api_key_env: str,
) -> LLM:
    try:
        from llama_index.llms.openai import OpenAI
    except ImportError as exc:
        raise ImportError("pip install llama-index-llms-openai") from exc

    api_key = os.getenv(api_key_env, "local")
    if not api_key:
        raise OSError(
            f"{api_key_env} not set. Add it to ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env"
        )

    return OpenAI(
        model=model_id,
        api_base=api_base,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )
