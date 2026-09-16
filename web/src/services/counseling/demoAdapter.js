import { validateCounselingUpload } from './uploadValidation.js'

const STORAGE_KEY = 'yuxi:counseling-workspace-demo:v1'
const SCHEMA_VERSION = 1
const clone = (value) => JSON.parse(JSON.stringify(value))
const stamp = () => new Date().toISOString()
const unsupportedDemo = (capability) => ({ status: 'not_supported', capability, message: '演示模式不修改真实档案' })

const student = (overrides) => ({
  id: '', code: '', name: '', chiefConcern: '', riskLevel: 'normal', status: 'active',
  sessionCount: 0, nextAppointment: null, recentActivity: '', counselor: '陈老师', ...overrides,
})

/** 创建纯虚构的演示数据。 */
export function createCounselingDemoSeed() {
  return {
    version: SCHEMA_VERSION,
    workspaces: {
      'demo-001': {
        student: student({
          id: 'demo-001', code: 'S2026018', name: '林同学', chiefConcern: '考试压力与睡眠困扰',
          riskLevel: 'watch', sessionCount: 4, nextAppointment: '2026-09-18 14:00',
          recentActivity: '两天前提交睡眠记录', counselor: '陈老师',
        }),
        background: '大二学生。近期课程密度增加，入睡时间延后，希望建立稳定的复习与休息节奏。',
        todos: [
          { id: 'todo-1', title: '下次会谈核对睡眠记录', status: 'todo', dueAt: '2026-09-18' },
          { id: 'todo-2', title: '确认呼吸练习执行感受', status: 'todo' },
        ],
        timeline: [
          { id: 'session-2', occurredAt: '2026-09-11 14:00', title: '第 4 次辅导', summary: '识别睡前反刍触发点，练习将复习任务拆分到白天。', moodBefore: 7, moodAfter: 5, source: 'manual' },
          { id: 'session-1', occurredAt: '2026-09-04 14:00', title: '第 3 次辅导', summary: '梳理考试压力和睡眠变化，约定记录一周睡眠。', moodBefore: 8, moodAfter: 6, source: 'manual' },
        ],
        goals: [
          { id: 'goal-1', title: '建立可持续的睡前流程', progress: 60, status: 'active', homework: '连续 5 天记录上床时间与入睡感受' },
          { id: 'goal-2', title: '降低考前回避', progress: 35, status: 'active', homework: '每天完成一个 25 分钟复习单元' },
        ],
        assessments: [
          { name: '主观焦虑（0–10）', points: [{ date: '09-04', value: 8 }, { date: '09-11', value: 7 }], interpretation: '仍需关注，近一次略有下降。' },
          { name: '睡眠质量（0–10）', points: [{ date: '09-04', value: 4 }, { date: '09-11', value: 5 }], interpretation: '轻微改善，建议继续记录。' },
        ],
        crises: [
          { id: 'crisis-1', occurredAt: '2026-09-04', level: 'watch', signal: '连续失眠与明显疲惫', response: '已共同确认支持资源和紧急联系人，持续观察。', status: 'monitoring' },
        ],
        uploads: [],
        assistantMessages: [
          { id: 'msg-1', role: 'assistant', content: '我会只基于林同学当前档案中的演示资料协助准备。', createdAt: stamp() },
        ],
      },
      'demo-002': {
        student: student({
          id: 'demo-002', code: 'S2026042', name: '周同学', chiefConcern: '人际冲突与持续低落',
          riskLevel: 'high', sessionCount: 2, nextAppointment: '2026-09-17 10:30',
          recentActivity: '今天更新高风险关注', counselor: '王老师',
        }),
        background: '大一学生。宿舍关系紧张，近两周情绪持续低落。当前档案含需人工核对的高风险信息。',
        todos: [{ id: 'todo-3', title: '今日复核风险内容与支持资源', status: 'todo', dueAt: '2026-09-16' }],
        timeline: [{ id: 'session-3', occurredAt: '2026-09-15 10:30', title: '第 2 次辅导', summary: '讨论宿舍冲突与孤立感，完成支持资源盘点。', moodBefore: 9, moodAfter: 7, source: 'manual' }],
        goals: [{ id: 'goal-3', title: '恢复可获得的同伴支持', progress: 20, status: 'active', homework: '联系一位可信任同学' }],
        assessments: [{ name: '主观低落（0–10）', points: [{ date: '09-08', value: 7 }, { date: '09-15', value: 9 }], interpretation: '近期上升，需要人工复核风险。' }],
        crises: [{ id: 'crisis-2', occurredAt: '2026-09-15', level: 'high', signal: '表达无望感，风险内容待进一步核对', response: '已记录支持资源；本演示不代表危机干预已完成。', status: 'monitoring' }],
        uploads: [], assistantMessages: [],
      },
      'demo-003': {
        student: student({
          id: 'demo-003', code: 'S2025127', name: '许同学', chiefConcern: '生涯选择焦虑',
          riskLevel: 'normal', status: 'closed', sessionCount: 6, nextAppointment: null,
          recentActivity: '一个月前完成阶段回顾', counselor: '陈老师',
        }),
        background: '已完成阶段性辅导，保留结案前的目标与量表趋势。',
        todos: [], timeline: [], goals: [{ id: 'goal-4', title: '形成可执行的生涯探索计划', progress: 100, status: 'done', homework: '按月回顾计划' }],
        assessments: [], crises: [], uploads: [], assistantMessages: [],
      },
    },
  }
}

function defaultStorage() {
  if (typeof window !== 'undefined' && window.localStorage) return window.localStorage
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

/** 创建演示工作台适配器。 */
export function createCounselingDemoAdapter({ storage = defaultStorage() } = {}) {
  function read() {
    try {
      const saved = JSON.parse(storage.getItem(STORAGE_KEY) || 'null')
      if (saved?.version === SCHEMA_VERSION && saved.workspaces) return saved
    } catch {
      // 损坏的演示状态直接重建，不影响真实业务数据。
    }
    const seed = createCounselingDemoSeed()
    storage.setItem(STORAGE_KEY, JSON.stringify(seed))
    return seed
  }

  function write(state) {
    storage.setItem(STORAGE_KEY, JSON.stringify(state))
  }

  function workspaceOrThrow(state, id) {
    const workspace = state.workspaces[id]
    if (!workspace) throw new Error('未找到学生档案')
    return workspace
  }

  return {
    mode: 'demo',

    async listCounselors() { return unsupportedDemo('counselor_assignment') },
    async createStudent() { return unsupportedDemo('student_creation') },
    async createConversation() { return unsupportedDemo('conversation_creation') },

    async listStudents(filters = {}) {
      const query = String(filters.query || '').trim().toLowerCase()
      const items = Object.values(read().workspaces).map(({ student: item }) => item)
        .filter((item) => !query || [item.code, item.name, item.chiefConcern, item.counselor].some((value) => value.toLowerCase().includes(query)))
        .filter((item) => !filters.riskLevel || item.riskLevel === filters.riskLevel)
        .filter((item) => !filters.status || item.status === filters.status)
        .filter((item) => filters.appointment !== 'upcoming' || item.nextAppointment)
      return { status: 'ok', data: clone(items) }
    },

    async getWorkspace(studentId) {
      return { status: 'ok', data: clone(workspaceOrThrow(read(), studentId)) }
    },

    async updateStudent(studentId, patch) {
      const state = read()
      Object.assign(workspaceOrThrow(state, studentId).student, patch)
      write(state)
      return { status: 'ok', data: clone(state.workspaces[studentId]) }
    },

    async uploadRecord(studentId, file) {
      const validationError = validateCounselingUpload(file)
      if (validationError) return validationError
      const extension = String(file.name).split('.').pop().toLowerCase()
      const state = read()
      const workspace = workspaceOrThrow(state, studentId)
      const uploaded = {
        id: 'upload-' + Date.now(), name: file.name, size: file.size, type: extension,
        status: 'parsed', createdAt: stamp(),
        parsedPreview: '演示解析结果：来访者描述近期压力上升、睡眠不稳，并愿意尝试记录情绪与作息。',
      }
      workspace.uploads.unshift(uploaded)
      write(state)
      return { status: 'ok', data: clone(uploaded) }
    },

    async generateSummary(studentId, uploadId) {
      const workspace = workspaceOrThrow(read(), studentId)
      const draft = {
        id: 'draft-' + Date.now(), studentId, uploadId,
        emotion: '焦虑与疲惫交替，谈话后紧张程度有所下降。',
        coreIssue: workspace.student.riskLevel === 'high' ? '人际冲突、孤立感与无望感需要进一步核对。' : '考试压力与睡眠节律相互影响。',
        pattern: '压力升高时倾向延后处理任务，并在睡前反复思考。',
        riskAssessment: workspace.student.riskLevel === 'high' ? '演示识别为高风险；必须由辅导人员人工核对，不能视为已完成处置。' : '暂未识别到紧急风险，继续常规观察。',
        riskLevel: workspace.student.riskLevel,
        homework: '记录一周情绪、睡眠与触发事件。',
        nextPlan: '复核记录，讨论可执行的压力调节策略。',
      }
      return { status: 'ok', data: draft }
    },

    async saveDraft(studentId, draft) {
      workspaceOrThrow(read(), studentId)
      return { status: 'ok', data: clone(draft) }
    },

    async buildArchivePreview(studentId, draft) {
      const workspace = workspaceOrThrow(read(), studentId)
      const impacts = [
        { section: 'timeline', action: 'add', description: '新增 1 条辅导记录与前后变化' },
        { section: 'goals', action: 'update', description: '更新当前目标，并记录家庭作业' },
        { section: 'assessments', action: workspace.assessments[0] ? 'update' : 'add', description: '补充 1 个主观情绪观察点' },
        { section: 'todos', action: 'add', description: '新增下次谈话准备待办' },
      ]
      if (draft.riskLevel !== 'normal') {
        impacts.push({ section: 'crisis', action: 'add', description: '新增风险观察记录（不代表已完成危机处置）' })
      }
      return { status: 'ok', data: { draftId: draft.id, impacts, requiresRiskAcknowledgement: draft.riskLevel === 'high' } }
    },

    async archiveSummary(studentId, draft, { riskAcknowledged = false } = {}) {
      if (draft.riskLevel === 'high' && !riskAcknowledged) {
        return { status: 'error', code: 'risk_ack_required', message: '请先确认已人工核对风险内容' }
      }
      const state = read()
      const workspace = workspaceOrThrow(state, studentId)
      const id = Date.now()
      workspace.timeline.unshift({
        id: 'session-' + id, occurredAt: stamp().slice(0, 16).replace('T', ' '),
        title: '第 ' + (workspace.student.sessionCount + 1) + ' 次辅导',
        summary: draft.coreIssue + ' ' + draft.nextPlan, moodBefore: 7, moodAfter: 5, source: 'upload',
      })
      workspace.student.sessionCount += 1
      workspace.student.recentActivity = '刚刚归档了谈话记录（演示）'
      workspace.todos.unshift({ id: 'todo-' + id, title: draft.nextPlan, status: 'todo' })
      if (workspace.goals[0]) workspace.goals[0].homework = draft.homework
      if (draft.riskLevel !== 'normal') {
        workspace.crises.unshift({
          id: 'crisis-' + id, occurredAt: stamp().slice(0, 10), level: draft.riskLevel,
          signal: draft.riskAssessment, response: '已归档人工审阅结果；仍需按机构流程处理。', status: 'monitoring',
        })
      }
      const assessmentPoint = { date: stamp().slice(5, 10), value: 6 }
      if (workspace.assessments[0]) {
        workspace.assessments[0].points.push(assessmentPoint)
      } else {
        workspace.assessments.push({
          name: '主观情绪观察',
          points: [assessmentPoint],
          interpretation: '演示观察点，不替代标准化量表。',
        })
      }
      write(state)
      return { status: 'ok', data: clone(workspace) }
    },

    async sendAssistantMessage(studentId, content, context = {}) {
      workspaceOrThrow(read(), studentId)
      const reply = context.intent === 'prepare'
        ? '建议先核对最近待办与风险观察，再从上次家庭作业的执行感受开始。'
        : context.intent === 'next_step'
          ? '建议把这个话题拆成三步：先核对事实与近期变化，再明确一个本次可执行动作，最后约定下次复盘点。所有建议都需要辅导人员结合原始记录确认。'
        : context.intent === 'adjust'
          ? '可以把摘要中的事实观察与推测分开，并保留需要当面核对的表述。'
          : '当前回答仅基于此学生的演示档案，不包含外部知识库结论。'
      const assistantMessage = { id: 'msg-a-' + Date.now(), role: 'assistant', content: reply, createdAt: stamp() }
      return { status: 'ok', data: clone(assistantMessage) }
    },

    async resetDemo() {
      const seed = createCounselingDemoSeed()
      write(seed)
      return { status: 'ok', data: clone(seed) }
    },
  }
}

export { STORAGE_KEY }
