"""档案驱动 AI 协作的纯逻辑边界。"""

import io
import zipfile
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from counseling.ai_work import service
from counseling.ai_work.service import (
    _stable_snapshot,
    _validate_material_bytes,
    confirm_material,
    get_material_content,
    import_material,
)


def _student(**changes):
    values = {
        "id": 1,
        "student_code": "S-001",
        "display_name": "学生一",
        "class_name": "一班",
        "background_summary": "已确认背景",
        "status": "active",
        "current_risk_level": "watch",
        "version": 3,
        "closure_note": None,
        "closed_at": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_snapshot_contains_confirmed_facts_in_stable_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """快照只由正式记录、更正和人工风险组成，顺序及指纹稳定。"""
    first = datetime(2026, 9, 1, 1, 0)
    second = datetime(2026, 9, 2, 1, 0)
    records = [
        SimpleNamespace(
            id="r2",
            record_kind="manual",
            consulted_at=second,
            consultation_type="面谈",
            source_file_name=None,
            source_content_type=None,
            source_size=None,
            source_sha256=None,
            parsed_text="二",
            summary=None,
            content={"overview": "二"},
            confirmed_at=second,
        ),
        SimpleNamespace(
            id="r1",
            record_kind="manual",
            consulted_at=first,
            consultation_type="面谈",
            source_file_name=None,
            source_content_type=None,
            source_size=None,
            source_sha256=None,
            parsed_text="一",
            summary=None,
            content={"overview": "一"},
            confirmed_at=first,
        ),
    ]
    corrections = [
        SimpleNamespace(
            id="c1",
            record_id="r1",
            reason="更正",
            corrected_content={"overview": "更正后"},
            created_at=second,
        )
    ]
    risks = [
        SimpleNamespace(
            id="risk1",
            level="watch",
            basis="人工判断",
            action_taken="跟进",
            status="monitoring",
            source_record_id="r1",
            created_at=second,
        )
    ]

    monkeypatch.setattr("counseling.ai_work.service.utc_now_naive", lambda: first)
    snapshot_a, digest_a = _stable_snapshot(_student(), records, corrections, risks)
    monkeypatch.setattr("counseling.ai_work.service.utc_now_naive", lambda: second)
    snapshot_b, digest_b = _stable_snapshot(_student(), list(reversed(records)), corrections, risks)

    assert [item["id"] for item in snapshot_a["formal_records"]] == ["r1", "r2"]
    assert snapshot_a["student"]["background_summary"] == "已确认背景"
    assert snapshot_a["corrections"][0]["corrected_content"] == {"overview": "更正后"}
    assert snapshot_a["risk_events"][0]["basis"] == "人工判断"
    assert "drafts" not in snapshot_a
    assert "raw_files" not in snapshot_a
    assert "conversations" not in snapshot_a
    assert "personal_notes" not in snapshot_a
    assert snapshot_a["captured_at"] != snapshot_b["captured_at"]
    assert digest_a == digest_b


def _docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "content_type"),
    [
        ("note.txt", "中文".encode(), "text/plain"),
        ("note.md", b"# title", "text/markdown"),
        ("report.pdf", b"%PDF-1.7\n", "application/pdf"),
        (
            "report.docx",
            _docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_material_whitelist_and_signatures(name: str, data: bytes, content_type: str) -> None:
    """四类允许文件通过真实字节边界校验。"""
    assert _validate_material_bytes(name, data) == (name, content_type)


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("bad.exe", b"MZ"),
        ("bad.pdf", b"not pdf"),
        ("bad.docx", b"PK-not-zip"),
        ("bad.txt", b"\xff"),
        ("../bad.txt", b"text"),
    ],
)
def test_material_validation_rejects_unsafe_or_mismatched_files(name: str, data: bytes) -> None:
    """路径、编码、签名或白名单不匹配时 fail-closed。"""
    with pytest.raises((ValueError, UnicodeDecodeError)):
        _validate_material_bytes(name, data)


@pytest.mark.asyncio
async def test_material_upload_failure_keeps_recoverable_intent_without_review_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对象上传失败只保留可恢复导入意图，不发布待审核或审计成功。"""
    actor = SimpleNamespace(id=7, uid="counselor-7", department_id=3, business_roles=["counselor"])
    work_item = SimpleNamespace(status="ready", conversation_thread_id="thread-1")
    captured: list[object] = []
    db = SimpleNamespace(
        add=captured.append,
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class FakeRepository:
        material = None

        async def get_material_by_request(self, department_id, counselor_id, request_id):
            return None

        async def get_work_item(self, *args, **kwargs):
            return work_item

        async def get_material_by_source(self, *args, **kwargs):
            return self.material

        async def require_presented_artifact(self, *args, **kwargs):
            return None

        def add(self, item):
            self.material = item
            db.add(item)

    repository = FakeRepository()
    monkeypatch.setattr(service, "CounselingAIWorkRepository", lambda _db: repository)
    monkeypatch.setattr(
        service,
        "StudentRepository",
        lambda _db: SimpleNamespace(get_for_owner=AsyncMock(return_value=object())),
    )
    port = SimpleNamespace(read_artifact=AsyncMock(return_value=b"synthetic material"))
    storage = SimpleNamespace(upload=AsyncMock(side_effect=RuntimeError("synthetic upload failure")))

    with pytest.raises(RuntimeError, match="synthetic upload failure"):
        await import_material(
            db,
            actor,
            11,
            "work-item-1",
            request_id="request_1234",
            run_id="run-1",
            path="report.txt",
            port=port,
            storage=storage,
        )

    assert repository.material.status == "importing"
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_material_content_and_confirmation_fail_closed_on_incomplete_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """导入中对象不可读，损坏对象也不能确认成正式材料。"""
    actor = SimpleNamespace(id=7, department_id=3, business_roles=["counselor"])
    item = SimpleNamespace(
        status="importing",
        bucket="materials",
        object_name="item.txt",
        size=3,
        sha256="0" * 64,
        confirmation_key=None,
    )

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def get_material(self, *args, **kwargs):
            return item

    monkeypatch.setattr(service, "CounselingAIWorkRepository", FakeRepository)
    monkeypatch.setattr(
        service,
        "StudentRepository",
        lambda _db: SimpleNamespace(get_for_owner=AsyncMock(return_value=object())),
    )
    storage = SimpleNamespace(download=AsyncMock(return_value=b"bad"))
    db = SimpleNamespace(add=lambda _item: None, commit=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(LookupError, match="材料不存在"):
        await get_material_content(db, actor, 11, "material-1", storage)
    storage.download.assert_not_awaited()

    item.status = "pending_review"
    with pytest.raises(service.AIWorkConflictError, match="完整性校验失败"):
        await confirm_material(
            db,
            actor,
            11,
            "material-1",
            "confirm_1234",
            storage,
        )

    storage.download.side_effect = service.CounselingObjectStorageError(
        "synthetic missing object"
    )
    with pytest.raises(service.AIWorkConflictError, match="暂时不可读取"):
        await confirm_material(
            db,
            actor,
            11,
            "material-1",
            "confirm_1234",
            storage,
        )

    assert item.status == "pending_review"
    db.commit.assert_not_awaited()

@pytest.mark.asyncio
async def test_project_context_only_binds_metadata_without_writing_projection(monkeypatch):
    """创建 WorkItem 时只登记元数据，私有投影必须延迟到 Run 执行边界。"""
    from counseling.integrations import yuxi as yuxi_integration

    conversation = SimpleNamespace(
        uid="counselor-1",
        extra_metadata={"counseling": {"student_id": 11, "work_item_id": "work-1"}},
    )
    repository = SimpleNamespace(
        get_conversation_by_thread_id=AsyncMock(return_value=conversation)
    )
    monkeypatch.setattr(
        yuxi_integration,
        "ConversationRepository",
        lambda _db: repository,
    )
    filesystem_call = AsyncMock(side_effect=AssertionError("创建阶段不得写投影文件"))
    monkeypatch.setattr(yuxi_integration.asyncio, "to_thread", filesystem_call)
    db = SimpleNamespace(commit=AsyncMock())

    path = await yuxi_integration.YuxiConversationAdapter().project_context(
        db=db,
        actor=SimpleNamespace(uid="counselor-1"),
        thread_id="thread-1",
        instruction="整理跟进计划",
        snapshot={"student": {"id": 11}},
    )

    assert path == "/.counseling/confirmed-context.json"
    assert conversation.extra_metadata["counseling"]["context_path"] == path
    assert conversation.extra_metadata["model_context"]["payload"]["confirmed_context_path"] == path
    db.commit.assert_awaited_once()
    filesystem_call.assert_not_awaited()

@pytest.mark.asyncio
async def test_material_reads_write_minimal_success_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """材料列表和正文成功返回前必须持久化不含正文或路径的最小审计。"""
    actor = SimpleNamespace(id=7, department_id=3, business_roles=["counselor"])
    item = SimpleNamespace(
        id="material-1",
        work_item_id="work-1",
        source_run_id="run-1",
        source_artifact_path="/private/report.txt",
        file_name="report.txt",
        content_type="text/plain",
        size=6,
        sha256="a" * 64,
        status="pending_review",
        bucket="materials",
        object_name="opaque-object",
        created_at=None,
        confirmed_at=None,
    )

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def get_material(self, *args, **kwargs):
            return item

        async def list_materials(self, *args, **kwargs):
            return [item]

    monkeypatch.setattr(service, "CounselingAIWorkRepository", FakeRepository)
    monkeypatch.setattr(
        service,
        "StudentRepository",
        lambda _db: SimpleNamespace(get_for_owner=AsyncMock(return_value=object())),
    )
    captured: list[object] = []
    db = SimpleNamespace(add=captured.append, commit=AsyncMock())
    storage = SimpleNamespace(download=AsyncMock(return_value=b"secret"))

    returned_item, data = await service.get_material_content(
        db, actor, 11, "material-1", storage
    )
    materials = await service.list_materials(db, actor, 11)

    assert returned_item is item and data == b"secret"
    assert materials[0]["id"] == "material-1"
    assert [event.action for event in captured] == [
        "material.content.read",
        "material.list",
    ]
    assert captured[0].event_metadata == {"material_id": "material-1"}
    assert captured[1].event_metadata == {"count": 1}
    assert all("secret" not in str(event.event_metadata) for event in captured)
    assert db.commit.await_count == 2
