"""用独立标注样本计算 AI 风险提示质量门禁。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskHintEvaluation:
    """冻结阈值、混淆矩阵和是否通过产品门禁。"""

    threshold: float
    true_positive: int
    false_negative: int
    false_positive: int
    true_negative: int
    recall: float
    false_positive_rate: float
    passed: bool


def evaluate_risk_hints(labels: list[bool], scores: list[float], *, threshold: float) -> RiskHintEvaluation:
    """按固定分母计算召回率和假阳性率，空分母时显式失败。"""
    if len(labels) != len(scores) or not labels:
        raise ValueError("标注与评分必须等长且不能为空")
    if not 0 <= threshold <= 1:
        raise ValueError("阈值必须在 0 到 1 之间")
    if any(not isinstance(label, bool) for label in labels):
        raise ValueError("标注必须全部是布尔值")
    if any(isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1 for score in scores):
        raise ValueError("评分必须是 0 到 1 之间的数值")

    predictions = [score >= threshold for score in scores]
    true_positive = sum(label and prediction for label, prediction in zip(labels, predictions, strict=True))
    false_negative = sum(label and not prediction for label, prediction in zip(labels, predictions, strict=True))
    false_positive = sum(not label and prediction for label, prediction in zip(labels, predictions, strict=True))
    true_negative = sum(not label and not prediction for label, prediction in zip(labels, predictions, strict=True))
    positive_count = true_positive + false_negative
    negative_count = false_positive + true_negative
    if positive_count == 0 or negative_count == 0:
        raise ValueError("独立标注集必须同时包含阳性和阴性样本")
    recall = true_positive / positive_count
    false_positive_rate = false_positive / negative_count
    return RiskHintEvaluation(
        threshold=threshold,
        true_positive=true_positive,
        false_negative=false_negative,
        false_positive=false_positive,
        true_negative=true_negative,
        recall=recall,
        false_positive_rate=false_positive_rate,
        passed=recall >= 0.95 and false_positive_rate <= 0.05,
    )
