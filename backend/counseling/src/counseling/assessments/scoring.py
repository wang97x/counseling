"""固定版本量表目录与确定性计分。"""

PHQ9_CODE = "phq9"
PHQ9_VERSION = 1
PHQ9_ITEMS = (
    "做事兴趣或乐趣减少",
    "感到心情低落、沮丧或绝望",
    "入睡困难、睡不安稳或睡眠过多",
    "感觉疲倦或缺乏精力",
    "食欲不振或吃得过多",
    "觉得自己很糟或让自己、家人失望",
    "难以集中注意力",
    "动作或说话变慢，或烦躁坐立不安",
    "出现伤害自己的念头",
)


def get_scale_catalog() -> list[dict]:
    """返回当前可施测的冻结量表定义。"""
    return [
        {
            "code": PHQ9_CODE,
            "version": PHQ9_VERSION,
            "name": "PHQ-9",
            "items": list(PHQ9_ITEMS),
            "options": [
                {"value": 0, "label": "完全没有"},
                {"value": 1, "label": "有几天"},
                {"value": 2, "label": "一半以上时间"},
                {"value": 3, "label": "几乎每天"},
            ],
            "notice": "结果仅供辅导员结合实际情况审阅，不构成诊断，也不会自动改变风险等级。",
        }
    ]


def score_phq9(answers: object) -> tuple[list[int], int, str]:
    """校验九项答案并返回冻结答案、总分和分段。"""
    if not isinstance(answers, list) or len(answers) != len(PHQ9_ITEMS):
        raise ValueError("PHQ-9 必须提交 9 项完整答案")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 3 for value in answers):
        raise ValueError("PHQ-9 每项答案必须是 0 到 3 的整数")
    normalized = list(answers)
    total = sum(normalized)
    if total <= 4:
        severity = "minimal"
    elif total <= 9:
        severity = "mild"
    elif total <= 14:
        severity = "moderate"
    elif total <= 19:
        severity = "moderately_severe"
    else:
        severity = "severe"
    return normalized, total, severity
