"""AI 风险提示质量门禁与人工核实用例。"""

import hashlib
import json
import math
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.continuity.repository import ContinuityRepository
from counseling.identity.models import User
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.identity.services.audit import log_operation
from counseling.risk_hints.evaluation import RiskHintEvaluation, evaluate_risk_hints
from counseling.risk_hints.repository import RiskHintRepository
from counseling.storage.models import CounselingAuditEvent, CounselingRiskHint, CounselingRiskHintEvaluation
from counseling.students.repository import StudentRepository
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive


class RiskHintConflictError(Exception):
    """表示风险提示幂等意图、版本或状态冲突。"""


def _key(value: str) -> str:
    value = value.strip()
    if not 8 <= len(value) <= 64 or not all(char.isalnum() or char in "_-" for char in value):
        raise ValueError("request_id格式无效")
    return value


def _text(value: str, field: str, *, max_length: int) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field}不能为空")
    if len(value) > max_length:
        raise ValueError(f"{field}过长")
    return value


def _score(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("风险提示评分必须是 0 到 1 之间的有限数值")
    return float(value)


def _require_manager(actor: User) -> int:
    if BusinessCapability.VIEW_DEPARTMENT_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要业务管理权限")
    if actor.department_id is None:
        raise ValueError("当前用户未绑定部门")
    return actor.department_id


async def _owned_student(db: AsyncSession, actor: User, student_id: int, *, for_update: bool = False):
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    student = await StudentRepository(db).get_for_owner(
        student_id, actor.department_id, actor.id, for_update=for_update
    )
    if student is None:
        raise LookupError("学生档案不存在")
    return student


def _evaluation_fingerprint(labels: list[bool], scores: list[float], threshold: float) -> str:
    payload = json.dumps(
        {"labels": labels, "scores": scores, "threshold": threshold},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _evaluation_payload(item: CounselingRiskHintEvaluation) -> dict:
    return {
        "id": item.id,
        "dataset_reference": item.dataset_reference,
        "dataset_fingerprint": item.dataset_fingerprint,
        "model_reference": item.model_reference,
        "threshold": item.threshold,
        "true_positive": item.true_positive,
        "false_negative": item.false_negative,
        "false_positive": item.false_positive,
        "true_negative": item.true_negative,
        "recall": item.recall,
        "false_positive_rate": item.false_positive_rate,
        "passed": item.passed,
        "created_by": item.created_by,
        "created_at": format_utc_datetime(item.created_at),
    }


def _evaluation_matches(
    item: CounselingRiskHintEvaluation,
    dataset_reference: str,
    model_reference: str,
    fingerprint: str,
    result: RiskHintEvaluation,
) -> bool:
    return (
        item.dataset_reference == dataset_reference
        and item.model_reference == model_reference
        and item.dataset_fingerprint == fingerprint
        and item.threshold == result.threshold
        and item.true_positive == result.true_positive
        and item.false_negative == result.false_negative
        and item.false_positive == result.false_positive
        and item.true_negative == result.true_negative
    )


async def publish_evaluation(
    db: AsyncSession,
    actor: User,
    *,
    request_id: str,
    dataset_reference: str,
    model_reference: str,
    threshold: float,
    labels: list[bool],
    scores: list[float],
) -> dict:
    """计算并发布不含样本正文的部门风险提示质量门禁。"""
    department_id = _require_manager(actor)
    request_id = _key(request_id)
    dataset_reference = _text(dataset_reference, "数据集引用", max_length=256)
    model_reference = _text(model_reference, "模型引用", max_length=256)
    result = evaluate_risk_hints(labels, scores, threshold=threshold)
    fingerprint = _evaluation_fingerprint(labels, [float(score) for score in scores], result.threshold)
    repository = RiskHintRepository(db)
    existing = await repository.get_evaluation_by_request(department_id, request_id)
    if existing is not None:
        if not _evaluation_matches(existing, dataset_reference, model_reference, fingerprint, result):
            raise RiskHintConflictError("request_id 已用于不同评测意图")
        return _evaluation_payload(existing)
    item = CounselingRiskHintEvaluation(
        id=uuid.uuid4().hex,
        department_id=department_id,
        dataset_reference=dataset_reference,
        dataset_fingerprint=fingerprint,
        model_reference=model_reference,
        threshold=result.threshold,
        true_positive=result.true_positive,
        false_negative=result.false_negative,
        false_positive=result.false_positive,
        true_negative=result.true_negative,
        recall=result.recall,
        false_positive_rate=result.false_positive_rate,
        passed=result.passed,
        created_by=actor.id,
        request_id=request_id,
    )
    repository.add(item)
    await log_operation(
        db,
        actor.id,
        "counseling.risk_hint_evaluation.publish",
        details=json.dumps(
            {"evaluation_id": item.id, "department_id": department_id, "passed": result.passed},
            separators=(",", ":"),
        ),
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await repository.get_evaluation_by_request(department_id, request_id)
        if existing is not None and _evaluation_matches(
            existing, dataset_reference, model_reference, fingerprint, result
        ):
            return _evaluation_payload(existing)
        raise RiskHintConflictError("风险提示评测发布发生并发冲突") from exc
    await db.refresh(item)
    return _evaluation_payload(item)


async def list_evaluations(db: AsyncSession, actor: User) -> list[dict]:
    """列出本部门不含样本正文的质量门禁历史。"""
    department_id = _require_manager(actor)
    items = await RiskHintRepository(db).list_evaluations(department_id)
    await log_operation(
        db,
        actor.id,
        "counseling.risk_hint_evaluation.list",
        details=json.dumps({"department_id": department_id, "count": len(items)}, separators=(",", ":")),
    )
    await db.commit()
    return [_evaluation_payload(item) for item in items]


def _hint_payload(item: CounselingRiskHint) -> dict:
    return {
        "id": item.id,
        "student_id": item.student_id,
        "evaluation_id": item.evaluation_id,
        "protocol_id": item.protocol_id,
        "source_work_item_id": item.source_work_item_id,
        "source_run_id": item.source_run_id,
        "source_message_id": item.source_message_id,
        "score": item.score,
        "evidence_summary": item.evidence_summary,
        "status": item.status,
        "decision_note": item.decision_note,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": format_utc_datetime(item.reviewed_at),
        "version": item.version,
        "created_at": format_utc_datetime(item.created_at),
        "requires_manual_risk_event": item.status == "accepted",
    }


def _hint_matches(
    item: CounselingRiskHint,
    student_id: int,
    evaluation_id: str,
    protocol_id: str,
    source_work_item_id: str,
    source_run_id: str,
    score: float,
    evidence_summary: str,
) -> bool:
    return (
        item.student_id == student_id
        and item.evaluation_id == evaluation_id
        and item.protocol_id == protocol_id
        and item.source_work_item_id == source_work_item_id
        and item.source_run_id == source_run_id
        and item.score == score
        and item.evidence_summary == evidence_summary
    )


async def create_risk_hint(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    evaluation_id: str,
    source_work_item_id: str,
    source_run_id: str,
) -> dict:
    """仅在质量门禁和部门协议均有效时创建待人工核实提示。"""
    request_id = _key(request_id)
    await _owned_student(db, actor, student_id)
    repository = RiskHintRepository(db)
    existing = await repository.get_hint_by_request(actor.id, request_id)
    if existing is not None:
        if not _hint_matches(
            existing, student_id, evaluation_id, existing.protocol_id,
            source_work_item_id, source_run_id, existing.score, existing.evidence_summary
        ):
            raise RiskHintConflictError("request_id 已用于不同风险提示意图")
        return _hint_payload(existing)
    student = await _owned_student(db, actor, student_id, for_update=True)
    if student.status != "active":
        raise ValueError("已结束档案不能新增风险提示")
    evaluation = await repository.get_evaluation(evaluation_id, actor.department_id)
    if evaluation is None or not evaluation.passed:
        raise ValueError("风险提示评测未通过质量门禁")
    output = await repository.get_verified_run_output(
        source_work_item_id,
        source_run_id,
        student_id,
        actor.department_id,
        actor.id,
        actor.uid,
    )
    if output is None:
        raise ValueError("风险提示来源不是当前档案已完成 Run 的显式输出")
    run, message = output
    model_reference = str((run.input_payload or {}).get("model_spec") or "").strip()
    if model_reference != evaluation.model_reference:
        raise ValueError("风险提示来源模型与已发布评测不一致")
    try:
        model_output = json.loads(message.content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("风险提示模型输出必须是严格 JSON") from exc
    if not isinstance(model_output, dict) or set(model_output) != {
        "schema_version", "score", "evidence_summary"
    } or model_output["schema_version"] != 1:
        raise ValueError("风险提示模型输出结构无效")
    score = _score(model_output["score"])
    evidence_summary = _text(model_output["evidence_summary"], "触发依据", max_length=10000)
    if score < evaluation.threshold:
        raise ValueError("评分未达到已发布评测阈值")
    protocol = await ContinuityRepository(db).get_active_protocol(actor.department_id, utc_now_naive())
    if protocol is None:
        raise ValueError("当前部门缺少生效中的危机协议")
    item = CounselingRiskHint(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        evaluation_id=evaluation.id,
        protocol_id=protocol.id,
        source_work_item_id=source_work_item_id,
        source_run_id=source_run_id,
        source_message_id=message.id,
        score=score,
        evidence_summary=evidence_summary,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="risk_hint.create",
            outcome="success",
            event_metadata={"evaluation_id": evaluation.id, "protocol_id": protocol.id},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await repository.get_hint_by_request(actor.id, request_id)
        if existing is not None and _hint_matches(
            existing, student_id, evaluation_id, existing.protocol_id,
            source_work_item_id, source_run_id, score, evidence_summary
        ):
            return _hint_payload(existing)
        raise RiskHintConflictError("风险提示创建发生并发冲突") from exc
    await db.refresh(item)
    return _hint_payload(item)


async def list_risk_hints(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出负责人档案内的风险提示与人工核实结果。"""
    await _owned_student(db, actor, student_id)
    items = await RiskHintRepository(db).list_hints(student_id, actor.department_id, actor.id)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="risk_hint.list",
            outcome="success",
            event_metadata={"count": len(items)},
        )
    )
    await db.commit()
    return [_hint_payload(item) for item in items]


async def review_risk_hint(
    db: AsyncSession,
    actor: User,
    student_id: int,
    hint_id: str,
    *,
    request_id: str,
    expected_version: int,
    decision: str,
    note: str,
) -> dict:
    """由档案负责人采纳或拒绝提示，但不自动创建风险事件或工单。"""
    request_id = _key(request_id)
    if decision not in {"accepted", "rejected"}:
        raise ValueError("风险提示核实决定无效")
    note = _text(note, "核实说明", max_length=10000)
    await _owned_student(db, actor, student_id)
    repository = RiskHintRepository(db)
    replay = await repository.get_hint_by_decision_request(actor.id, request_id)
    if replay is not None:
        if not (
            replay.id == hint_id
            and replay.student_id == student_id
            and replay.status == decision
            and replay.decision_note == note
        ):
            raise RiskHintConflictError("request_id 已用于不同核实意图")
        return _hint_payload(replay)
    item = await repository.get_hint_for_owner(
        hint_id, student_id, actor.department_id, actor.id, for_update=True
    )
    if item is None:
        raise LookupError("风险提示不存在")
    replay = await repository.get_hint_by_decision_request(actor.id, request_id)
    if replay is not None:
        if not (
            replay.id == hint_id
            and replay.student_id == student_id
            and replay.status == decision
            and replay.decision_note == note
        ):
            raise RiskHintConflictError("request_id 已用于不同核实意图")
        return _hint_payload(replay)
    if item.version != expected_version or item.status != "pending_review":
        raise RiskHintConflictError("风险提示版本已变化或已完成核实")
    item.status = decision
    item.decision_note = note
    item.reviewed_by = actor.id
    item.reviewed_at = utc_now_naive()
    item.decision_request_id = request_id
    item.version += 1
    item.updated_at = utc_now_naive()
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action=f"risk_hint.{decision}",
            outcome="success",
            event_metadata={"hint_id": hint_id},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        replay = await repository.get_hint_by_decision_request(actor.id, request_id)
        if replay is not None and replay.id == hint_id and replay.status == decision and replay.decision_note == note:
            return _hint_payload(replay)
        raise RiskHintConflictError("风险提示核实发生并发冲突") from exc
    return _hint_payload(item)
