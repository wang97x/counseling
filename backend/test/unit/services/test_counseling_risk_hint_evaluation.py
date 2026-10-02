"""AI 风险提示独立评测的固定分母测试。"""

import pytest
from counseling.risk_hints.evaluation import evaluate_risk_hints


def test_risk_hint_gate_passes_only_at_fixed_quality_targets() -> None:
    """召回率和假阳性率同时达到目标才通过。"""
    labels = [True] * 20 + [False] * 20
    scores = [0.9] * 19 + [0.1] + [0.9] + [0.1] * 19

    result = evaluate_risk_hints(labels, scores, threshold=0.5)

    assert result.recall == 0.95
    assert result.false_positive_rate == 0.05
    assert result.passed is True


def test_risk_hint_gate_rejects_false_positive_rate_above_target() -> None:
    """误报率使用全部真实阴性样本作分母。"""
    labels = [True] * 20 + [False] * 20
    scores = [0.9] * 20 + [0.9, 0.9] + [0.1] * 18

    result = evaluate_risk_hints(labels, scores, threshold=0.5)

    assert result.false_positive == 2
    assert result.false_positive_rate == 0.1
    assert result.passed is False


@pytest.mark.parametrize(
    ("labels", "scores"),
    [([], []), ([True], []), ([True, True], [0.9, 0.8]), ([False, False], [0.1, 0.2])],
)
def test_risk_hint_gate_fails_closed_for_invalid_or_one_sided_sets(labels, scores) -> None:
    """空数据、不等长或单边标注集不能伪装成质量通过。"""
    with pytest.raises(ValueError):
        evaluate_risk_hints(labels, scores, threshold=0.5)


def test_risk_hint_gate_rejects_invalid_score_and_threshold() -> None:
    """评分与阈值越界时在评测边界拒绝。"""
    with pytest.raises(ValueError):
        evaluate_risk_hints([True, False], [1.1, 0.1], threshold=0.5)
    with pytest.raises(ValueError):
        evaluate_risk_hints([True, False], [0.9, 0.1], threshold=-0.1)


@pytest.mark.parametrize("invalid_label", ["false", None, 0, object()])
def test_risk_hint_gate_rejects_non_boolean_labels(invalid_label) -> None:
    """字符串、空值和数值不能按 truthiness 污染标注分母。"""
    with pytest.raises(ValueError, match="布尔值"):
        evaluate_risk_hints([True, False, invalid_label], [0.9, 0.1, 0.1], threshold=0.5)
