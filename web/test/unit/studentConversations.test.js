import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  filterApiStudents,
  mapApiStudent,
  mapApiTimelineNode,
  toApiStudentPatch,
} from '../../src/domains/counseling/services/apiMapping.js'
import {
  createLatestOperation,
  isCurrentStudentRequest,
} from '../../src/domains/counseling/requestGuard.js'

test('API 映射保留 closed 与负责人边界，不伪造风险和未接入字段', () => {
  const owner = mapApiStudent({
    id: 9,
    student_code: 'S-9',
    counselor_id: 7,
    status: 'closed',
    current_risk_level: 'urgent',
    background_summary: '',
    version: 4,
  })
  assert.equal(owner.status, 'closed')
  assert.equal(owner.riskLevel, 'urgent')
  assert.equal(owner.version, 4)
  assert.equal(owner.sessionCount, null)
  assert.equal(owner.counselorId, 7)
  assert.equal(owner.chiefConcern, '尚未录入主诉')

  const managerRow = mapApiStudent({ id: 10, student_code: 'S-10', counselor_id: 8, status: 'active' })
  assert.equal(managerRow.chiefConcern, '打开档案查看')
  assert.deepEqual(filterApiStudents([owner, managerRow], { status: 'closed', query: 'S-9' }), [owner])
  assert.deepEqual(toApiStudentPatch({
    chiefConcern: '更新背景', status: 'closed', displayName: '学生甲', className: '一班',
  }), {
    background_summary: '更新背景',
    display_name: '学生甲',
    class_name: '一班',
  })
})

test('正式记录时间线展示结构化摘要且不暴露 source 对象为标签', () => {
  assert.deepEqual(mapApiTimelineNode({
    id: 'record-1',
    type: 'record',
    occurred_at: '2026-09-22T10:00:00Z',
    title: '谈话记录.pdf',
    source: { file_name: '谈话记录.pdf' },
    summary: { sections: [{ title: '会谈概述', content: '已由辅导员确认' }] },
  }), {
    id: 'record-1',
    conversationId: undefined,
    occurredAt: '2026-09-22T10:00:00Z',
    title: '谈话记录.pdf',
    summary: '会谈概述：已由辅导员确认',
    type: 'record',
    source: 'upload',
    content: null,
    recordId: undefined,
    riskLevel: undefined,
    riskStatus: undefined,
  })
})

test('真实时间线会话 DTO 使用节点 id 保留继续对话入口', () => {
  assert.deepEqual(mapApiTimelineNode({
    id: 'thread-2',
    type: 'conversation',
    occurred_at: '2026-09-22T11:00:00Z',
    title: '第 2 次辅导',
    agent_id: 'counseling-agent',
  }), {
    id: 'thread-2',
    conversationId: 'thread-2',
    occurredAt: '2026-09-22T11:00:00Z',
    title: '第 2 次辅导',
    summary: '暂无摘要',
    type: 'conversation',
    source: 'assistant',
    content: null,
    recordId: undefined,
    riskLevel: undefined,
    riskStatus: undefined,
  })
})

test('手工记录、追加更正和人工风险节点保留业务语义', () => {
  const manual = mapApiTimelineNode({
    id: 'manual-1',
    type: 'consultation_record',
    title: '面谈记录',
    occurred_at: '2026-09-24T02:00:00Z',
    content: { overview: '人工记录概述', next_plan: '继续跟进' },
  })
  assert.equal(manual.source, 'manual')
  assert.equal(manual.summary, '人工记录概述')
  assert.equal(manual.content.next_plan, '继续跟进')

  const correction = mapApiTimelineNode({
    id: 'correction-1',
    type: 'record_correction',
    record_id: 'manual-1',
    summary: '补充人工核对',
    content: { overview: '更正后内容' },
  })
  assert.equal(correction.source, 'correction')
  assert.equal(correction.recordId, 'manual-1')

  const risk = mapApiTimelineNode({
    id: 'risk-1', type: 'risk_event', summary: '人工判断依据', risk_level: 'watch', risk_status: 'monitoring',
  })
  assert.equal(risk.source, 'risk')
  assert.equal(risk.riskLevel, 'watch')
  assert.equal(risk.riskStatus, 'monitoring')
})

test('学生请求守卫拒绝切换档案或代次后的迟到结果', () => {
  assert.equal(isCurrentStudentRequest('1', 4, '1', 4), true)
  assert.equal(isCurrentStudentRequest('1', 4, '2', 5), false)
  assert.equal(isCurrentStudentRequest('1', 4, '1', 5), false)
})

test('旧操作失效后新学生仍可拥有独立 loading 代次', () => {
  const operations = createLatestOperation()
  const oldOperation = operations.begin()
  operations.invalidate()
  assert.equal(operations.isCurrent(oldOperation), false)
  const newOperation = operations.begin()
  assert.equal(operations.isCurrent(newOperation), true)
  assert.equal(operations.isCurrent(oldOperation), false)
})

test('列表逆序响应只提交最新筛选结果且旧请求不能提前结束 loading', async () => {
  const operations = createLatestOperation()
  let resolveOld
  let resolveNew
  let visible = ''
  let loading = false

  async function commit(value, wait) {
    const operation = operations.begin()
    loading = true
    await wait
    if (!operations.isCurrent(operation)) return
    visible = value
    loading = false
  }

  const oldGate = new Promise((resolve) => { resolveOld = resolve })
  const newGate = new Promise((resolve) => { resolveNew = resolve })
  const oldRequest = commit('旧筛选', oldGate)
  const newRequest = commit('新筛选', newGate)
  resolveNew()
  await newRequest
  assert.equal(visible, '新筛选')
  assert.equal(loading, false)
  resolveOld()
  await oldRequest
  assert.equal(visible, '新筛选')
  assert.equal(loading, false)
})

test('前端服务只装配真实适配器且没有演示回退', () => {
  const selector = readFileSync(new URL('../../src/domains/counseling/workspaceService.js', import.meta.url), 'utf8')
  const apiAdapter = readFileSync(new URL('../../src/domains/counseling/services/apiAdapter.js', import.meta.url), 'utf8')
  assert.match(selector, /return createCounselingApiAdapter\(\)/)
  assert.doesNotMatch(selector, /VITE_COUNSELING_DEMO|createCounselingDemoAdapter/)
  assert.doesNotMatch(apiAdapter, /createCounselingDemoAdapter/)
})
