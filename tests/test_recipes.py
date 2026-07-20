"""Unit tests for harness.recipes (config loader, registry, EMA_CONFIG_DIR, build_recipe).

Offline: build_recipe is exercised with monkeypatched index/LLM factories + a fake
retriever, so no Neo4j / real model. The cross-encoder (pipeline) path is live-only.
"""

import textwrap
from types import SimpleNamespace

import pytest
from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

import harness.indexing as idx
import harness.llms as llms
from harness.recipes import (
    build_recipe,
    default_recipe_name,
    get_recipe,
    list_recipes,
    load_recipe,
)
from harness.recipes.config import FewshotPolicy, JudgePolicy, Recipe, _recipe_from_dict
from harness.schemas import RegulatoryAnswer

_BUILTINS = {
    "naive_rag", "crag_agentic", "react_agentic", "regulatory_agent",
    "agentic_reranked", "agentic_judged", "regulatory_fewshot", "tree_agent",
}


class _FakeRetriever(BaseRetriever):
    def __init__(self):
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle):
        return [NodeWithScore(node=TextNode(text="x", metadata={"source_url": "u"}), score=1.0)]


def _fake_profile(*_a, **_k):
    """A minimal stand-in for an IndexProfile (build_recipe reads profile.retrieval.k)."""
    return SimpleNamespace(retrieval=SimpleNamespace(k=10))


# --- config loading ---------------------------------------------------------


def test_builtin_recipes_load_and_register():
    names = set(list_recipes())
    assert _BUILTINS <= names


def test_default_recipe_is_naive_rag():
    assert default_recipe_name() == "naive_rag"


def test_load_recipe_fields():
    r = get_recipe("crag_agentic")
    assert r.tools == ["corrective_search", "ema_search"]
    assert r.output_schema == "RegulatoryAnswer"
    assert r.pipeline is None  # "none" -> None
    assert r.system_prompt == "agent_crag.md"


def test_pipeline_none_normalization():
    assert _recipe_from_dict("x", {"retrieval": {"pipeline": "none"}}).pipeline is None
    assert _recipe_from_dict("x", {"retrieval": {"pipeline": "native"}}).pipeline == "native"


def test_agentic_reranked_turns_pipeline_on():
    assert get_recipe("agentic_reranked").pipeline == "native"


# --- honest resolved attributes ---------------------------------------------


def test_resolved_attributes_are_honest():
    attrs = get_recipe("crag_agentic").resolved_attributes()
    assert attrs["ema.recipe"] == "crag_agentic"
    assert attrs["ema.orchestration.tools"] == "corrective_search,ema_search"
    assert attrs["ema.retrieval.pipeline"] == "none"
    assert attrs["ema.generation.model"] == "claude_opus"
    # policy flags are stamped, but a DISABLED stage carries no detail keys
    assert "ema.fewshot.enabled" in attrs
    assert "ema.judge.enabled" in attrs
    assert "ema.judge.judges" not in attrs
    assert "ema.fewshot.k" not in attrs


def test_resolved_attributes_enabled_stage_detail():
    r = Recipe(
        name="x",
        fewshot=FewshotPolicy(enabled=True, k=5),
        judge=JudgePolicy(enabled=True, judges=["faithfulness"]),
    )
    attrs = r.resolved_attributes()
    assert attrs["ema.fewshot.k"] == 5
    assert attrs["ema.judge.judges"] == "faithfulness"


def test_resolved_attributes_reflect_effective_overrides():
    # The trace must stamp what ACTUALLY ran (the live overrides), not the recipe default.
    r = get_recipe("naive_rag")  # model=claude_opus, temperature=0.0
    attrs = r.resolved_attributes(model="claude_haiku", temperature=0.5, retrieval_k=7)
    assert attrs["ema.generation.model"] == "claude_haiku"  # override, not recipe default
    assert attrs["ema.generation.temperature"] == 0.5
    assert attrs["ema.retrieval.k"] == 7
    # bare call (no overrides) falls back to recipe defaults and omits k
    bare = r.resolved_attributes()
    assert bare["ema.generation.model"] == "claude_opus"
    assert "ema.retrieval.k" not in bare


def test_fewshot_recipe_enables_injection():
    r = get_recipe("regulatory_fewshot")
    assert r.fewshot.enabled is True
    assert r.fewshot.min_rating == 4
    assert r.resolved_attributes()["ema.fewshot.enabled"] is True


# --- EMA_CONFIG_DIR external override ---------------------------------------


def test_external_config_dir_discovers_and_overrides(tmp_path, monkeypatch):
    rdir = tmp_path / "recipes"
    rdir.mkdir()
    (rdir / "my_custom.yaml").write_text(
        textwrap.dedent(
            """
            recipe:
              label: "My custom"
              orchestration: {tools: [ema_search]}
            """
        ),
        encoding="utf-8",
    )
    # shadow a built-in name
    (rdir / "naive_rag.yaml").write_text(
        "recipe:\n  label: OVERRIDDEN\n  orchestration: {tools: [ema_search]}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EMA_CONFIG_DIR", str(tmp_path))

    names = set(list_recipes())
    assert "my_custom" in names
    assert load_recipe("naive_rag").label == "OVERRIDDEN"  # external wins


# --- build_recipe wiring (offline) ------------------------------------------


def test_build_recipe_wires_agent_from_recipe(monkeypatch):
    fake_retriever = _FakeRetriever()
    monkeypatch.setattr(idx, "load_index_profile", _fake_profile)
    monkeypatch.setattr(idx, "build_retriever", lambda profile, index: fake_retriever)
    monkeypatch.setattr(llms, "get_llm_for_model", lambda model, temperature_override=None: MockLLM())

    adapter = build_recipe(get_recipe("crag_agentic"), index=None)
    agent = adapter._session.agent
    assert {t.metadata.name for t in agent.tools} == {"corrective_search", "ema_search"}
    assert agent.output_cls is RegulatoryAnswer
    # the resolved recipe is carried for honest trace stamping
    assert adapter._extra_attributes["ema.recipe"] == "crag_agentic"


def test_build_recipe_naive_single_tool(monkeypatch):
    fake_retriever = _FakeRetriever()
    monkeypatch.setattr(idx, "load_index_profile", _fake_profile)
    monkeypatch.setattr(idx, "build_retriever", lambda profile, index: fake_retriever)
    monkeypatch.setattr(llms, "get_llm_for_model", lambda model, temperature_override=None: MockLLM())

    adapter = build_recipe(get_recipe("naive_rag"), index=None)
    assert {t.metadata.name for t in adapter._session.agent.tools} == {"ema_search"}
    assert isinstance(get_recipe("naive_rag"), Recipe)


def test_fewshot_min_examples_tunable_and_stamped():
    # F7: min_examples is a recipe knob (default 1 — a hardcoded 3 made injection
    # unreachable for k<3 recipes) and is stamped when fewshot is enabled.
    assert FewshotPolicy.from_dict({}).min_examples == 1
    policy = FewshotPolicy.from_dict({"enabled": True, "k": 2, "min_examples": 2})
    assert policy.min_examples == 2
    r = get_recipe("regulatory_fewshot")
    assert r.fewshot.min_examples == 1
    assert r.resolved_attributes()["ema.fewshot.min_examples"] == 1


def test_fewshot_unknown_source_rejected():
    # Only the rated cache exists; a recipe must not claim a source that doesn't (F10).
    with pytest.raises(ValueError, match="fewshot.source"):
        FewshotPolicy.from_dict({"source": "mlflow_rated"})


def test_routing_key_parsed_and_stamped():
    r = get_recipe("steered_agent")
    assert r.routing == "default"
    assert r.index_profile == "neo4j_steered"
    attrs = r.resolved_attributes()
    assert attrs["ema.retrieval.routing"] == "default"


def test_routing_defaults_to_none_and_stamps_honestly():
    r = get_recipe("naive_rag")
    assert r.routing is None
    assert r.resolved_attributes()["ema.retrieval.routing"] == "none"


def test_topic_agent_recipe_parses_subgraph_policy():
    r = get_recipe("topic_agent")
    assert "topic_context" in r.tools
    assert r.subgraph.context == "chunks"
    assert r.subgraph.max_tokens == 4000
    assert r.subgraph.page_size == 25
    attrs = r.resolved_attributes()
    assert attrs["ema.retrieval.subgraph.context"] == "chunks"
    assert attrs["ema.retrieval.subgraph.hubs"] == "default"
    assert attrs["ema.retrieval.subgraph.max_tokens"] == 4000


def test_subgraph_stamps_none_without_the_tool():
    r = get_recipe("steered_agent")
    assert r.resolved_attributes()["ema.retrieval.subgraph"] == "none"


def test_subgraph_keys_without_tool_rejected():
    # The keys only configure topic_context — declaring them without the tool
    # would stamp a layer that cannot run.
    with pytest.raises(ValueError, match="topic_context"):
        _recipe_from_dict("x", {"retrieval": {"subgraph": {"context": "map"}}})


def test_subgraph_unknown_context_rejected():
    from harness.retrieval.subgraphs import SubgraphPolicy

    with pytest.raises(ValueError, match="subgraph.context"):
        SubgraphPolicy.from_dict({"context": "summaries"})


def test_tree_agent_recipe_wires_tree_profile():
    r = get_recipe("tree_agent")
    assert r.index_profile == "neo4j_tree"
    assert r.tools == ["ema_search", "resolve_substance"]
    assert r.routing is None  # traversal showcase: no routing prior
    assert r.pipeline is None
