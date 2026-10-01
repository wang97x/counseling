"""固定版本量表计分的独立样例。"""

import pytest

from counseling.assessments.scoring import get_scale_catalog, score_phq9


@pytest.mark.parametrize(
    ("answers", "total", "severity"),
    [
        ([0] * 9, 0, "minimal"),
        ([1, 1, 1, 1, 1, 0, 0, 0, 0], 5, "mild"),
        ([1, 1, 1, 1, 0, 0, 0, 0, 0], 4, "minimal"),
        ([1, 1, 1, 1, 1, 1, 1, 1, 2], 10, "moderate"),
        ([1] * 9, 9, "mild"),
        ([2, 2, 2, 2, 2, 2, 1, 1, 1], 15, "moderately_severe"),
        ([2, 2, 2, 2, 2, 1, 1, 1, 1], 14, "moderate"),
        ([3, 2, 2, 2, 2, 2, 2, 2, 2], 19, "moderately_severe"),
        ([3, 3, 2, 2, 2, 2, 2, 2, 2], 20, "severe"),
        ([3] * 9, 27, "severe"),
    ],
)
def test_phq9_scores_fixed_v1_boundaries(answers, total, severity) -> None:
    """独立样例固定各分段边界与最大分。"""
    assert score_phq9(answers) == (answers, total, severity)


@pytest.mark.parametrize("answers", [[0] * 8, [0] * 10, [-1] + [0] * 8, [4] + [0] * 8, [False] + [0] * 8])
def test_phq9_rejects_incomplete_or_invalid_answers(answers) -> None:
    """漏项、超项、越界和布尔值都不能进入计分。"""
    with pytest.raises(ValueError):
        score_phq9(answers)


def test_catalog_freezes_code_version_and_nine_items() -> None:
    """目录公开与计分 Owner 相同的冻结版本。"""
    catalog = get_scale_catalog()
    assert [(item["code"], item["version"], len(item["items"])) for item in catalog] == [("phq9", 1, 9)]
    assert "不构成诊断" in catalog[0]["notice"]
