"""Unit tests for harness.eval.bootstrap + judges (pure parts)."""

from harness.eval import Exemplar, generate_exemplars, judge_filter
from harness.eval.judges import align_judge, load_judge_instructions
from harness.schemas import RegulatoryAnswer


def test_judge_filter_threshold():
    exemplars = [Exemplar("q1", "a", 5.0), Exemplar("q2", "a", 3.0), Exemplar("q3", "a", 4.0)]
    kept = judge_filter(exemplars, min_score=4.0)
    assert [e.question for e in kept] == ["q1", "q3"]


def test_generate_exemplars_with_fake_teacher_and_judge():
    def teacher(question):
        return RegulatoryAnswer(answer=f"ans:{question}", confidence=0.5)

    def judge(question, _prediction):
        return 5.0 if "good" in question else 2.0

    exemplars = generate_exemplars(["good q", "bad q"], teacher=teacher, judge=judge)
    assert len(exemplars) == 2
    assert exemplars[0].answer == "ans:good q"
    kept = judge_filter(exemplars, min_score=4.0)
    assert len(kept) == 1
    assert kept[0].question == "good q"


def test_generate_exemplars_without_judge_scores_zero():
    exemplars = generate_exemplars(["q"], teacher=lambda _q: RegulatoryAnswer(answer="a"))
    assert exemplars[0].score == 0.0


def test_load_judge_instructions_missing_raises():
    try:
        load_judge_instructions("does_not_exist_judge")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")


def test_align_judge_without_align_method_raises():
    try:
        align_judge(object(), traces=[])
    except NotImplementedError:
        pass
    else:
        raise AssertionError("expected NotImplementedError")
