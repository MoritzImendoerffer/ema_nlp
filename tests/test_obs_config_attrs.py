"""Unit tests for harness.obs.config_attrs (transparency / no silent modes)."""

from harness.obs import echo_resolved_config, resolved_config_attributes, stamp_current_span


def test_flatten_nested_config():
    cfg = {
        "retrieval": {
            "query_transform": "synonym",
            "graph_mode": "none",
            "k": 20,
            "sub_retrievers": ["vector", "cypher"],
            "rerank": None,
        },
        "agent": {"name": "regulatory", "streaming": True},
    }
    attrs = resolved_config_attributes(cfg)
    assert attrs["ema.retrieval.query_transform"] == "synonym"
    assert attrs["ema.retrieval.graph_mode"] == "none"
    assert attrs["ema.retrieval.k"] == 20
    assert attrs["ema.retrieval.sub_retrievers"] == "vector,cypher"
    assert attrs["ema.retrieval.rerank"] == "none"  # None -> explicit "none"
    assert attrs["ema.agent.streaming"] is True


def test_empty_list_becomes_none():
    attrs = resolved_config_attributes({"x": {"y": []}})
    assert attrs["ema.x.y"] == "none"


def test_custom_prefix():
    attrs = resolved_config_attributes({"a": 1}, prefix="run")
    assert attrs["run.a"] == 1


def test_stamp_current_span_noop_without_recording_span():
    # No active recording span in a unit test → returns False, never raises.
    assert stamp_current_span({"ema.x": "y"}) is False


def test_echo_returns_summary_line():
    line = echo_resolved_config({"retrieval": {"k": 5}})
    assert "ema.retrieval.k=5" in line
