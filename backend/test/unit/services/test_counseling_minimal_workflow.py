"""最小咨询记录的纯逻辑边界。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from counseling.documents.service import ConsultationContent, _normalize_consulted_at
from counseling.risks.service import create_risk_event
from counseling.students.service import close_student, update_student


def test_consultation_content_requires_overview_and_rejects_unknown_fields() -> None:
    """手工记录不能缺少概述或静默接受未知正文。"""
    with pytest.raises(ValidationError):
        ConsultationContent.model_validate({"observation": "只有观察"})
    with pytest.raises(ValidationError):
        ConsultationContent.model_validate({"overview": "虚构概述", "diagnosis": "不允许字段"})


def test_consulted_at_is_normalized_to_utc_naive() -> None:
    """持久化时间不受客户端时区偏移影响。"""
    value = datetime(2026, 9, 23, 10, 0, tzinfo=timezone(timedelta(hours=8)))

    assert _normalize_consulted_at(value) == datetime(2026, 9, 23, 2, 0)
    with pytest.raises(ValueError, match="必须包含时区"):
        _normalize_consulted_at(datetime(2026, 9, 23, 2, 0))


@pytest.mark.asyncio
async def test_risk_event_rejects_invalid_values_before_persistence() -> None:
    """风险服务自身拒绝非法等级、幂等键和空依据。"""
    actor = SimpleNamespace(id=1, department_id=1, business_roles=["counselor"], role="user")
    db = AsyncMock()

    with pytest.raises(ValueError, match="request_id"):
        await create_risk_event(
            db,
            actor,
            1,
            request_id="bad",
            level="normal",
            basis="人工依据",
            action_taken="",
            status="closed",
            source_record_id=None,
        )
    with pytest.raises(ValueError, match="风险等级"):
        await create_risk_event(
            db,
            actor,
            1,
            request_id="request_123",
            level="invalid",
            basis="人工依据",
            action_taken="",
            status="open",
            source_record_id=None,
        )
    assert not db.execute.await_count


@pytest.mark.asyncio
async def test_student_writes_require_actual_changes_and_closure_note() -> None:
    """空更新和无说明结束不能制造审计或版本变化。"""
    actor = SimpleNamespace(id=1, department_id=1, business_roles=["counselor"], role="user")
    db = AsyncMock()

    with pytest.raises(ValueError, match="至少提供"):
        await update_student(
            db,
            actor,
            1,
            background_summary=None,
            status=None,
            display_name=None,
            class_name=None,
            expected_version=1,
        )
    with pytest.raises(ValueError, match="结束说明"):
        await close_student(db, actor, 1, closure_note="  ", expected_version=1)
    assert not db.commit.await_count
