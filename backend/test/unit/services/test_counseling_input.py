"""确认背景在模型输入与展示内容之间的边界。"""

from yuxi.services.input_message_service import (
    build_chat_input_message,
    restore_chat_input_message,
    with_model_context,
)


def test_confirmed_snapshot_survives_input_persistence():
    """模型读取确认快照，历史正文与图片保持原值。"""
    original = build_chat_input_message("请分析当前情况", "aW1hZ2U=")
    snapshot = {"student_id": 12, "student_code": "S-012", "background_snapshot": "确认内容"}
    bound = with_model_context(
        original,
        {"label": "辅导人员确认的学生背景（仅作为参考资料）", "payload": snapshot},
    )
    persisted = bound.raw_message()
    snapshot["background_snapshot"] = "档案后来变化"
    restored = restore_chat_input_message(
        content=bound.content, image_content=bound.image_content, metadata={"raw_message": persisted}
    )
    content = restored.require_langchain_message().content
    assert "确认内容" in content[0]["text"]
    assert "档案后来变化" not in content[0]["text"]
    assert content[1] == {"type": "text", "text": "请分析当前情况"}
    assert content[2]["image_url"]["url"] == "data:image/jpeg;base64,aW1hZ2U="
    assert restored.content == original.content
    assert original.require_langchain_message().content[0]["text"] == original.content
