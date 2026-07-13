"""Unit tests for harness.retrieval.hubs (loader, validation, textual edits).

Offline: hubs files are written to tmp dirs; seed resolution is a mocked
callable (the store check runs in scripts/manage_topic_hubs.py live).
"""

from __future__ import annotations

import pytest

from harness.retrieval.hubs import (
    HubWalk,
    confirm_in_text,
    load_hubs,
    proposal_snippet,
    validate_seeds,
)

_VALID = """\
hubs:
  - key: referral_procedures
    seed_url: https://www.ema.europa.eu/en/hub-a
    status: confirmed
    proposed_by: sme
    walk:
      hops: 2
      categories: [qa, regulatory_overview]
      doc_types: []
      exclude_audience: [Veterinary]
  - key: gvp
    seed_url: https://www.ema.europa.eu/en/hub-b
    status: proposed
    proposed_by: discovery
    walk:
      hops: 1
      categories: []
      doc_types: [scientific-guideline]
"""


def _write(tmp_path, text, name="default"):
    (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_load_valid_file(tmp_path):
    config = load_hubs(config_dir=_write(tmp_path, _VALID))
    assert config.keys() == ["referral_procedures", "gvp"]
    assert [h.key for h in config.confirmed()] == ["referral_procedures"]
    hub = config.get("referral_procedures")
    assert hub.walk.hops == 2
    assert hub.walk.categories == ("qa", "regulatory_overview")
    assert hub.walk.exclude_audience == ("Veterinary",)


def test_config_hash_covers_confirmed_walk_params_only(tmp_path):
    base = load_hubs(config_dir=_write(tmp_path, _VALID)).config_hash()
    # changing a PROPOSED hub's walk must not change the build hash
    tweaked_proposed = _VALID.replace("hops: 1", "hops: 3")
    assert load_hubs(config_dir=_write(tmp_path, tweaked_proposed)).config_hash() == base
    # changing a CONFIRMED hub's walk must
    tweaked_confirmed = _VALID.replace("hops: 2", "hops: 3")
    assert load_hubs(config_dir=_write(tmp_path, tweaked_confirmed)).config_hash() != base


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (("hops: 2", "hops: 0"), "hops must be >= 1"),
        (("status: confirmed", "status: live"), "unknown status"),
        (("proposed_by: sme", "proposed_by: bot"), "unknown proposed_by"),
        (("categories: [qa, regulatory_overview]", "categories: [not_a_category]"),
         "unknown categor"),
        (("key: gvp", "key: referral_procedures"), "duplicate hub key"),
        (("seed_url: https://www.ema.europa.eu/en/hub-a", "seed_url: ftp://x"),
         "absolute http"),
    ],
)
def test_invalid_files_fail_loudly(tmp_path, mutation, match):
    old, new = mutation
    with pytest.raises(ValueError, match=match):
        load_hubs(config_dir=_write(tmp_path, _VALID.replace(old, new)))


def test_unqualified_walk_rejected(tmp_path):
    # empty categories AND doc_types = the news-pollution trap — hard error
    text = _VALID.replace("categories: [qa, regulatory_overview]", "categories: []")
    with pytest.raises(ValueError, match="qualifier"):
        load_hubs(config_dir=_write(tmp_path, text))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_hubs("nope", config_dir=tmp_path)


def test_external_config_dir_shadows_builtin(tmp_path, monkeypatch):
    (tmp_path / "hubs").mkdir()
    (tmp_path / "hubs" / "default.yaml").write_text(_VALID, encoding="utf-8")
    monkeypatch.setenv("EMA_CONFIG_DIR", str(tmp_path))
    assert load_hubs().keys() == ["referral_procedures", "gvp"]


def test_builtin_default_hubs_load():
    config = load_hubs()
    assert "referral_procedures" in [h.key for h in config.confirmed()]


def test_validate_seeds_names_the_dangling_hub(tmp_path):
    config = load_hubs(config_dir=_write(tmp_path, _VALID))
    validate_seeds(config, resolve=lambda url: True)  # all fine
    with pytest.raises(ValueError, match="gvp"):
        validate_seeds(config, resolve=lambda url: url.endswith("hub-a"))


# --- textual edits (comment-preserving) --------------------------------------


def test_confirm_in_text_flips_only_the_named_hub(tmp_path):
    text = "# a load-bearing comment\n" + _VALID
    out = confirm_in_text(text, "gvp")
    assert "# a load-bearing comment" in out  # comments survive
    config = load_hubs(config_dir=_write(tmp_path, out))
    assert {h.key for h in config.confirmed()} == {"referral_procedures", "gvp"}


def test_confirm_in_text_rejects_unknown_and_already_confirmed():
    with pytest.raises(ValueError, match="not found"):
        confirm_in_text(_VALID, "nope")
    with pytest.raises(ValueError, match="already confirmed"):
        confirm_in_text(_VALID, "referral_procedures")


def test_proposal_snippet_appends_as_valid_yaml(tmp_path):
    snippet = proposal_snippet(
        key="nitrosamines",
        seed_url="https://www.ema.europa.eu/en/hub-c",
        title="Nitrosamine impurities",
        score=42.0,
        walk=HubWalk(hops=2, categories=("qa",)),
    )
    _write(tmp_path, _VALID + "\n" + snippet)
    config = load_hubs(config_dir=tmp_path)
    hub = config.get("nitrosamines")
    assert hub is not None and hub.status == "proposed" and hub.proposed_by == "discovery"
    assert hub.walk.categories == ("qa",)
    assert hub not in config.confirmed()
