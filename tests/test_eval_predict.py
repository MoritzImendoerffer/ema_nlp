"""Unit tests for harness.eval.predict (predict_fn adapter)."""

from harness.eval import build_predict_fn
from harness.schemas import Citation, RegulatoryAnswer


class _FakeSession:
    def run(self, question):
        return RegulatoryAnswer(
            answer=f"A:{question}", citations=[Citation(source_url="u1")], confidence=0.7
        )


def test_build_predict_fn_from_session():
    fn = build_predict_fn(_FakeSession())
    out = fn("what is the NDMA AI?")
    assert out["answer"] == "A:what is the NDMA AI?"
    assert out["citations"] == ["u1"]
    assert out["confidence"] == 0.7
    assert out["num_claims"] == 0


def test_build_predict_fn_from_callable():
    fn = build_predict_fn(lambda _q: RegulatoryAnswer(answer="x"))
    assert fn("q")["answer"] == "x"
