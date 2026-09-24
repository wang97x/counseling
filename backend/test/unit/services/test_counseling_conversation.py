"""档案关联会话的业务端口边界。"""

from types import SimpleNamespace

from counseling.students import service


async def test_student_conversation_passes_trusted_snapshot_through_port(monkeypatch) -> None:
    """业务用例校验档案后只向通用平台传递固定快照。"""
    actor = SimpleNamespace(uid="counselor-1")
    calls: list[dict] = []

    async def get_student(_db, _actor, student_id):
        return {"id": student_id, "student_code": "S-001", "background_summary": "数据库背景"}

    class FakePort:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return {"id": "thread-1"}

    monkeypatch.setattr(service, "get_student", get_student)

    result = await service.create_student_conversation(
        object(),
        actor,
        7,
        agent_slug="main",
        request_id="request-1",
        title="辅导会话",
        background_snapshot="辅导员确认背景",
        port=FakePort(),
    )

    assert result == {"id": "thread-1"}
    assert calls[0]["server_metadata"] == {
        "counseling": {
            "student_id": 7,
            "student_code": "S-001",
            "background_snapshot": "辅导员确认背景",
        },
        "model_context": {
            "label": "辅导人员确认的学生背景（仅作为参考资料）",
            "payload": {
                "student_id": 7,
                "student_code": "S-001",
                "background_snapshot": "辅导员确认背景",
            },
        },
    }
