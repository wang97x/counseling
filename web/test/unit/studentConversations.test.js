import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { filterApiStudents, mapApiConversation, mapApiStudent, toApiStudentPatch } from '../../src/services/counseling/apiMapping.js'
import { validateCounselingUpload } from '../../src/services/counseling/uploadValidation.js'
import {
  createLatestOperation,
  isCurrentCounselingOperation,
  isCurrentStudentRequest,
} from '../../src/utils/counselingRequestGuard.js'
import { processCounselingRecordUpload } from '../../src/services/counseling/recordUploadFlow.js'
import {
  createCounselingDemoAdapter,
  createCounselingDemoSeed,
  STORAGE_KEY,
} from '../../src/services/counseling/demoAdapter.js'

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

test('演示模式初始化、筛选和重置使用版本化本地状态', async () => {
  const storage = memoryStorage()
  const service = createCounselingDemoAdapter({ storage })
  const initial = await service.listStudents()
  assert.equal(service.mode, 'demo')
  assert.equal(initial.data.length, 3)
  assert.equal(JSON.parse(storage.getItem(STORAGE_KEY)).version, 1)

  const filtered = await service.listStudents({ query: '睡眠', riskLevel: 'watch', appointment: 'upcoming' })
  assert.deepEqual(filtered.data.map((item) => item.id), ['demo-001'])

  const broken = memoryStorage({ [STORAGE_KEY]: '{"version":0}' })
  const repaired = createCounselingDemoAdapter({ storage: broken })
  await repaired.listStudents()
  assert.equal(JSON.parse(broken.getItem(STORAGE_KEY)).version, 1)

  await service.updateStudent('demo-001', { chiefConcern: '已修改' })
  await service.resetDemo()
  assert.equal((await service.getWorkspace('demo-001')).data.student.chiefConcern, createCounselingDemoSeed().workspaces['demo-001'].student.chiefConcern)
})

test('共享上传边界在真实请求前拒绝错误类型、空文件和超过 5MB 的文件', async () => {
  assert.equal(validateCounselingUpload({ name: 'talk.mp3', size: 10 }).code, 'invalid_type')
  assert.equal(validateCounselingUpload({ name: 'talk.txt', size: 0 }).code, 'empty_file')
  assert.equal(validateCounselingUpload({ name: 'talk.pdf', size: 5 * 1024 * 1024 + 1 }).code, 'file_too_large')
  assert.equal(validateCounselingUpload({ name: 'talk.docx', size: 10 }), null)

  const apiAdapter = readFileSync(new URL('../../src/services/counseling/apiAdapter.js', import.meta.url), 'utf8')
  assert.ok(apiAdapter.indexOf('validateCounselingUpload(file)') < apiAdapter.indexOf('uploadTmpAttachment(file)'))
})

test('真实附件成功后终止于明确的部分成功，不调用摘要或诱导重复上传', async () => {
  let uploadCalls = 0
  let summaryCalls = 0
  const service = {
    mode: 'api',
    async uploadRecord() {
      uploadCalls += 1
      return { status: 'ok', data: { id: 'attachment-1', name: '记录.pdf' } }
    },
    async generateSummary() {
      summaryCalls += 1
      return { status: 'not_supported' }
    },
  }

  const result = await processCounselingRecordUpload(service, 'student-1', { name: '记录.pdf' }, { threadId: 'thread-1' })
  assert.equal(result.status, 'ok')
  assert.equal(result.kind, 'attachment_only')
  assert.match(result.message, /附件已加入会话/)
  assert.equal(uploadCalls, 1)
  assert.equal(summaryCalls, 0)
})

test('上传拒绝错误类型、空文件和超过 5MB 的文件', async () => {
  const service = createCounselingDemoAdapter({ storage: memoryStorage() })
  assert.equal((await service.uploadRecord('demo-001', { name: 'talk.mp3', size: 10 })).code, 'invalid_type')
  assert.equal((await service.uploadRecord('demo-001', { name: 'talk.txt', size: 0 })).code, 'empty_file')
  assert.equal((await service.uploadRecord('demo-001', { name: 'talk.pdf', size: 5 * 1024 * 1024 + 1 })).code, 'file_too_large')
})

test('上传只持久化元数据，不保存文件二进制或自定义内容', async () => {
  const storage = memoryStorage()
  const service = createCounselingDemoAdapter({ storage })
  const result = await service.uploadRecord('demo-001', {
    name: '会谈记录.docx',
    size: 2048,
    secretBinary: 'DO_NOT_STORE',
  })
  assert.equal(result.status, 'ok')
  assert.equal(result.data.type, 'docx')
  assert.doesNotMatch(storage.getItem(STORAGE_KEY), /DO_NOT_STORE/)
})

test('摘要可编辑、预览影响并同步归档五个业务视图', async () => {
  const service = createCounselingDemoAdapter({ storage: memoryStorage() })
  const before = (await service.getWorkspace('demo-001')).data
  const upload = await service.uploadRecord('demo-001', { name: 'talk.txt', size: 100 })
  const generated = await service.generateSummary('demo-001', upload.data.id)
  const draft = { ...generated.data, homework: '修改后的家庭作业', riskLevel: 'watch' }
  assert.equal((await service.saveDraft('demo-001', draft)).data.homework, '修改后的家庭作业')

  const preview = await service.buildArchivePreview('demo-001', draft)
  assert.deepEqual(
    new Set(preview.data.impacts.map((item) => item.section)),
    new Set(['timeline', 'goals', 'assessments', 'crisis', 'todos']),
  )

  const archived = await service.archiveSummary('demo-001', draft)
  assert.equal(archived.status, 'ok')
  assert.equal(archived.data.timeline.length, before.timeline.length + 1)
  assert.equal(archived.data.crises.length, before.crises.length + 1)
  assert.equal(archived.data.todos.length, before.todos.length + 1)
  assert.equal(archived.data.goals[0].homework, '修改后的家庭作业')
  assert.equal(archived.data.assessments[0].points.length, before.assessments[0].points.length + 1)
})

test('无既有量表的演示档案按预览新增观察序列', async () => {
  const service = createCounselingDemoAdapter({ storage: memoryStorage() })
  const upload = await service.uploadRecord('demo-003', { name: 'talk.txt', size: 100 })
  const draft = (await service.generateSummary('demo-003', upload.data.id)).data
  const preview = await service.buildArchivePreview('demo-003', draft)
  const assessmentImpact = preview.data.impacts.find((item) => item.section === 'assessments')
  assert.equal(assessmentImpact.action, 'add')

  const archived = await service.archiveSummary('demo-003', draft)
  assert.equal(archived.data.assessments.length, 1)
  assert.equal(archived.data.assessments[0].points.length, 1)
})

test('API 映射保留 closed 与负责人边界，不伪造风险和未接入字段', () => {
  const owner = mapApiStudent({
    id: 9,
    student_code: 'S-9',
    counselor_id: 7,
    status: 'closed',
    background_summary: '',
  })
  assert.equal(owner.status, 'closed')
  assert.equal(owner.riskLevel, 'unknown')
  assert.equal(owner.sessionCount, null)
  assert.equal(owner.nextAppointment, undefined)
  assert.equal(owner.counselorId, 7)
  assert.equal(owner.chiefConcern, '尚未录入主诉')

  const managerRow = mapApiStudent({ id: 10, student_code: 'S-10', counselor_id: 8, status: 'active' })
  assert.equal(managerRow.chiefConcern, '打开档案查看')
  assert.deepEqual(filterApiStudents([owner, managerRow], { status: 'closed', query: 'S-9' }), [owner])
  assert.deepEqual(toApiStudentPatch({ chiefConcern: '更新背景', status: 'closed' }), {
    background_summary: '更新背景',
    status: 'closed',
  })
})

test('档案关联会话映射到可继续的时间轴节点', () => {
  assert.deepEqual(mapApiConversation({
    id: 'thread-1',
    title: '第 2 次辅导材料',
    created_at: '2026-09-17T12:00:00Z',
  }), {
    id: 'thread-1',
    conversationId: 'thread-1',
    occurredAt: '2026-09-17T12:00:00Z',
    title: '第 2 次辅导材料',
    summary: '暂无摘要',
    source: 'assistant',
  })
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

test('上传弹窗切换学生后拒绝旧学生的逆序完成结果', async () => {
  const operations = createLatestOperation()
  let currentStudentId = 'demo-001'
  let open = true
  let resolveOld
  let resolveNew
  let visible = ''

  async function commit(requestStudentId, value, wait) {
    const operation = operations.begin()
    await wait
    if (!isCurrentCounselingOperation(operations, operation, requestStudentId, currentStudentId, open)) return
    visible = value
  }

  const oldGate = new Promise((resolve) => { resolveOld = resolve })
  const newGate = new Promise((resolve) => { resolveNew = resolve })
  const oldRequest = commit('demo-001', '旧学生结果', oldGate)
  currentStudentId = 'demo-002'
  operations.invalidate()
  const newRequest = commit('demo-002', '新学生结果', newGate)
  resolveOld()
  await oldRequest
  assert.equal(visible, '')
  resolveNew()
  await newRequest
  assert.equal(visible, '新学生结果')
  open = false
  assert.equal(isCurrentCounselingOperation(operations, operations.begin(), currentStudentId, currentStudentId, open), false)
})

test('高风险摘要未人工确认时不能归档', async () => {
  const service = createCounselingDemoAdapter({ storage: memoryStorage() })
  const draft = (await service.generateSummary('demo-002', 'upload-demo')).data
  const preview = await service.buildArchivePreview('demo-002', draft)
  assert.equal(preview.data.requiresRiskAcknowledgement, true)
  assert.equal((await service.archiveSummary('demo-002', draft)).code, 'risk_ack_required')
  assert.equal((await service.archiveSummary('demo-002', draft, { riskAcknowledged: true })).status, 'ok')
})

test('前端服务边界显式选择适配器且生产模式没有演示回退', () => {
  const selector = readFileSync(new URL('../../src/services/counselingWorkspaceService.js', import.meta.url), 'utf8')
  const apiAdapter = readFileSync(new URL('../../src/services/counseling/apiAdapter.js', import.meta.url), 'utf8')
  assert.match(selector, /VITE_COUNSELING_DEMO/)
  assert.match(selector, /demo\s*\?\s*createCounselingDemoAdapter/)
  assert.match(apiAdapter, /status: 'not_supported'/)
  assert.doesNotMatch(apiAdapter, /createCounselingDemoAdapter/)
})

test('工作台使用 URL 标签恢复并隔离学生切换时的旧响应', () => {
  const source = readFileSync(new URL('../../src/views/StudentWorkspaceView.vue', import.meta.url), 'utf8')
  assert.match(source, /route\.query\.tab/)
  assert.match(source, /COUNSELING_TABS\.includes/)
  assert.match(source, /const version = \+\+requestVersion/)
  assert.match(source, /version !== requestVersion \|\| id !== studentId\.value/)
  assert.match(source, /isCurrentStudentRequest\(id, version, studentId\.value, requestVersion\)/)
  assert.match(source, /editOpen\.value = false/)
  assert.match(source, /conversationOpen\.value = false/)
  assert.match(source, /editBusy\.value = false/)
  assert.match(source, /conversationBusy\.value = false/)
  assert.match(source, /@click="openConversationCreator"/)
  assert.match(source, /<a-button v-if="service\.mode === 'api'" aria-label="打开下一步助手"/)
  assert.match(source, /<button v-if="service\.mode === 'api'" type="button" class="next-session"/)
  assert.match(source, /<button v-if="service\.mode === 'api'" type="button" @click="openConversationCreator"/)
  assert.doesNotMatch(source, /新建会话/)
  assert.match(source, /record\.source === 'assistant' \? '助手对话'/)
  assert.match(source, /record\.conversationId/)
  assert.match(source, />继续对话</)

  const listSource = readFileSync(new URL('../../src/views/StudentRecordListView.vue', import.meta.url), 'utf8')
  assert.match(listSource, /Number\(item\.counselorId\) === Number\(userStore\.userId\)/)
  assert.match(listSource, /仅负责人可打开/)
  assert.match(listSource, /const listOperations = createLatestOperation\(\)/)
  assert.match(listSource, /listOperations\.isCurrent\(operation\)/)
  assert.match(listSource, /service\.mode === 'api' \? '搜索编号或负责人'/)
  assert.match(listSource, /v-if="service\.mode === 'demo'" value="paused"/)
  assert.match(listSource, /aria-label="刷新档案列表"/)
  assert.match(listSource, /font-size: 0/)
  const apiAdapter = readFileSync(new URL('../../src/services/counseling/apiAdapter.js', import.meta.url), 'utf8')
  assert.match(apiAdapter, /timeline: items\.map\(mapApiConversation\)/)

  const uploadSource = readFileSync(new URL('../../src/components/counseling/RecordUploadFlow.vue', import.meta.url), 'utf8')
  assert.match(uploadSource, /\['上传记录', '附件已加入'\]/)
  assert.match(uploadSource, /completionMode\.value = result\.kind/)
  assert.match(uploadSource, /附件已加入最近会话/)
  assert.match(uploadSource, /AI 摘要与档案归档尚未发生/)
  assert.match(uploadSource, /completionMode === 'attachment_only' \? '关闭'/)
  assert.match(uploadSource, /flowOperations\.begin\(\)/)
  assert.match(uploadSource, /isCurrentCounselingOperation/)
})
