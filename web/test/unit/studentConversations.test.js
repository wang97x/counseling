import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'

function mountScript(api = {}) {
  const source = readFileSync(new URL('../../src/views/StudentRecordsView.vue', import.meta.url), 'utf8')
  const script = source.split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  const route = { params: { studentId: '1' } }
  const pushes = []
  const watches = []
  const state = runInNewContext(script + '\n;({loadDetail, saveDetail, createConversation, detail, editForm, conversationForm, conversations, error, conversationError})', {
    ref: (value) => ({ value }),
    computed: (get) => ({ get value() { return get() } }),
    watch: (_, callback) => watches.push(callback),
    useRoute: () => route,
    useRouter: () => ({ push: (value) => pushes.push(value) }),
    useUserStore: () => ({ businessRoles: ['counselor'], userId: 1 }),
    useAgentStore: () => ({ agents: [] }),
    counselingApi: { listConversations: async () => [], ...api },
    message: { success() {}, error() {} }
  })
  return { ...state, route, pushes, watches }
}

test('切换学生后晚到的旧详情不能覆盖当前档案或背景', async () => {
  let finishOld
  const state = mountScript({
    getStudent: (id) => id === '1'
      ? new Promise((resolve) => { finishOld = resolve })
      : Promise.resolve({ id: 2, background_summary: '学生二', status: 'active' })
  })
  const old = state.loadDetail('1')
  state.route.params.studentId = '2'
  await state.loadDetail('2')
  finishOld({ id: 1, background_summary: '学生一', status: 'active' })
  await old
  assert.equal(state.detail.value.id, 2)
  assert.equal(state.editForm.value.background_summary, '学生二')
})

test('旧学生保存结果和创建会话结果不能切回旧学生', async () => {
  let finishSave, finishCreate
  const state = mountScript({
    getStudent: async (id) => ({ id: Number(id), background_summary: '背景', status: 'active' }),
    updateStudent: () => new Promise((resolve) => { finishSave = resolve }),
    createConversation: () => new Promise((resolve) => { finishCreate = resolve })
  })
  await state.loadDetail('1')
  state.conversationForm.value = { student_id: 1, agent_id: 'agent', background_snapshot: '已确认' }
  const save = state.saveDetail()
  const create = state.createConversation()
  state.route.params.studentId = '2'
  await state.loadDetail('2')
  finishSave({ id: 1 })
  finishCreate({ id: 'old-thread' })
  await Promise.all([save, create])
  assert.equal(state.detail.value.id, 2)
  assert.equal(state.pushes.length, 0)
})

test('会话创建失败保留确认背景并显示可恢复错误', async () => {
  const state = mountScript({ createConversation: async () => { throw new Error('无权访问') } })
  state.conversationForm.value = { student_id: 1, agent_id: 'agent', background_snapshot: '确认内容' }
  await state.createConversation()
  assert.equal(state.conversationForm.value.background_snapshot, '确认内容')
  assert.equal(state.conversationError.value, '无权访问')
  assert.equal(state.pushes.length, 0)
})

test('新建成功进入返回的线程且保持确认学生', async () => {
  let saved
  const state = mountScript({ createConversation: async (payload) => { saved = payload; return { id: 'new-thread' } } })
  state.conversationForm.value = { student_id: 1, agent_id: 'agent', background_snapshot: '确认内容' }
  await state.createConversation()
  assert.equal(saved.student_id, 1)
  assert.equal(saved.background_snapshot, '确认内容')
  assert.equal(state.pushes[0].params.thread_id, 'new-thread')
})
