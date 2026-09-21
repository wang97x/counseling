<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Bot, CalendarClock, CheckCircle2, ClipboardList, FileUp,
  HeartPulse, History, ListChecks, MessageCirclePlus, PencilLine, RotateCcw, ShieldAlert, Target,
} from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AssessmentTrend from '@/components/counseling/AssessmentTrend.vue'
import CounselingAssistantDrawer from '@/components/counseling/CounselingAssistantDrawer.vue'
import RecordUploadFlow from '@/components/counseling/RecordUploadFlow.vue'
import RiskTag from '@/components/counseling/RiskTag.vue'
import { counselingWorkspaceService } from '@/services/counselingWorkspaceService.js'
import { buildNextStepTopics } from '@/services/counseling/nextStepTopics.js'
import { COUNSELING_TABS } from '@/types/counseling.js'
import { createLatestOperation, isCurrentStudentRequest } from '@/utils/counselingRequestGuard.js'
import { useAgentStore } from '@/stores/agent'
import { message } from 'ant-design-vue'

const route = useRoute()
const router = useRouter()
const service = counselingWorkspaceService
const agentStore = useAgentStore()
const workspace = ref(null)
const loading = ref(false)
const error = ref('')
const uploadOpen = ref(false)
const assistantOpen = ref(false)
const assistantBusy = ref(false)
const editOpen = ref(false)
const editBusy = ref(false)
const conversationOpen = ref(false)
const conversationBusy = ref(false)
const conversationError = ref('')
const editForm = reactive({ chiefConcern: '', status: 'active' })
const conversationForm = reactive({ agent_id: undefined })
const availableAgents = computed(() => agentStore.agents.filter((item) => !item.is_subagent))
let requestVersion = 0
const editOperations = createLatestOperation()
const conversationOperations = createLatestOperation()

const tabItems = [
  { key: 'overview', label: '概览', icon: ClipboardList },
  { key: 'timeline', label: '时间轴', icon: History },
  { key: 'goals', label: '目标与作业', icon: Target },
  { key: 'assessments', label: '量表', icon: HeartPulse },
  { key: 'crisis', label: '危机', icon: ShieldAlert },
]
const activeTab = computed(() => COUNSELING_TABS.includes(String(route.query.tab)) ? String(route.query.tab) : 'overview')
const studentId = computed(() => String(route.params.studentId || ''))
const nextStepTopics = computed(() => buildNextStepTopics(workspace.value))

async function loadWorkspace(id = studentId.value) {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  workspace.value = null
  try {
    const result = await service.getWorkspace(id)
    if (version !== requestVersion || id !== studentId.value) return
    if (result.status !== 'ok') throw new Error(result.message || '加载档案失败')
    workspace.value = result.data
  } catch (cause) {
    if (version === requestVersion) error.value = cause.message || '加载档案失败'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function setTab(tab) {
  if (!COUNSELING_TABS.includes(tab)) return
  void router.replace({ query: { ...route.query, tab } })
}

function openEdit() {
  editForm.chiefConcern = workspace.value.background || ''
  editForm.status = workspace.value.student.status
  editOpen.value = true
}

async function saveEdit() {
  const id = studentId.value
  const version = requestVersion
  const operation = editOperations.begin()
  editBusy.value = true
  try {
    const result = await service.updateStudent(id, { ...editForm })
    if (!isCurrentStudentRequest(id, version, studentId.value, requestVersion) || !editOperations.isCurrent(operation)) return
    if (result.status !== 'ok') throw new Error(result.message || '保存档案失败')
    workspace.value = result.data
    editOpen.value = false
    message.success('档案已保存')
  } catch (cause) {
    if (isCurrentStudentRequest(id, version, studentId.value, requestVersion) && editOperations.isCurrent(operation)) {
      message.error(cause.message || '保存档案失败')
    }
  } finally {
    if (editOperations.isCurrent(operation)) editBusy.value = false
  }
}

async function openConversationCreator() {
  const id = studentId.value
  const version = requestVersion
  const operation = conversationOperations.begin()
  conversationError.value = ''
  conversationForm.agent_id = undefined
  conversationOpen.value = true
  try {
    await agentStore.fetchAgents()
    if (!isCurrentStudentRequest(id, version, studentId.value, requestVersion) || !conversationOperations.isCurrent(operation)) return
    conversationForm.agent_id = availableAgents.value[0]?.id
  } catch (cause) {
    if (isCurrentStudentRequest(id, version, studentId.value, requestVersion) && conversationOperations.isCurrent(operation)) {
      conversationError.value = cause.message || '加载智能体失败'
    }
  }
}

async function createConversation() {
  const id = studentId.value
  const version = requestVersion
  const operation = conversationOperations.begin()
  if (!conversationForm.agent_id) {
    conversationError.value = '请选择可用的智能体'
    return
  }
  conversationBusy.value = true
  conversationError.value = ''
  try {
    const result = await service.createConversation({
      request_id: crypto.randomUUID(),
      student_id: Number(id),
      background_snapshot: workspace.value.background,
      title: workspace.value.student.code + ' · 辅导会话',
      agent_id: conversationForm.agent_id,
    })
    if (!isCurrentStudentRequest(id, version, studentId.value, requestVersion) || !conversationOperations.isCurrent(operation)) return
    if (result.status !== 'ok') throw new Error(result.message || '创建辅导会话失败')
    conversationOpen.value = false
    await router.push({
      name: 'AgentCompWithThreadId',
      params: { thread_id: result.data.id },
      query: { student_id: id },
    })
  } catch (cause) {
    if (isCurrentStudentRequest(id, version, studentId.value, requestVersion) && conversationOperations.isCurrent(operation)) {
      conversationError.value = cause.message || '创建辅导会话失败'
    }
  } finally {
    if (conversationOperations.isCurrent(operation)) conversationBusy.value = false
  }
}

async function resetDemo() {
  await service.resetDemo()
  await loadWorkspace()
}

function handleArchived(nextWorkspace) {
  workspace.value = nextWorkspace
}

async function sendAssistant({ content, intent }) {
  assistantBusy.value = true
  const id = studentId.value
  workspace.value.assistantMessages.push({
    id: 'local-user-' + Date.now(), role: 'user', content, createdAt: new Date().toISOString(),
  })
  try {
    const result = await service.sendAssistantMessage(id, content, { intent, tab: activeTab.value })
    if (id !== studentId.value) return
    if (result.status === 'not_supported') {
      workspace.value.assistantMessages.push({
        id: 'unsupported-' + Date.now(),
        role: 'assistant',
        content: result.message,
        createdAt: new Date().toISOString(),
      })
      return
    }
    if (result.status !== 'ok') throw new Error(result.message || '助手暂时不可用')
    if (id === studentId.value) workspace.value.assistantMessages.push(result.data)
  } catch (cause) {
    if (id === studentId.value) {
      workspace.value.assistantMessages.push({
        id: 'error-' + Date.now(), role: 'assistant',
        content: cause.message || '助手暂时不可用', createdAt: new Date().toISOString(),
      })
    }
  } finally {
    assistantBusy.value = false
  }
}

watch(studentId, (id) => {
  uploadOpen.value = false
  assistantOpen.value = false
  editOpen.value = false
  conversationOpen.value = false
  editOperations.invalidate()
  conversationOperations.invalidate()
  editBusy.value = false
  conversationBusy.value = false
  if (id) void loadWorkspace(id)
}, { immediate: true })
</script>

<template>
  <div class="workspace-page">
    <PageHeader :title="workspace?.student?.name ? workspace.student.name + '的档案' : '档案工作台'" :loading="loading" :show-border="true">
      <template #info><a-tag v-if="service.mode === 'demo'" color="gold">演示数据</a-tag></template>
      <template #actions>
        <a-button class="header-secondary" aria-label="返回档案列表" title="返回档案列表" @click="router.push('/students')">
          <template #icon><ArrowLeft :size="15" /></template><span>返回列表</span>
        </a-button>
        <a-button v-if="service.mode === 'demo'" class="header-secondary" aria-label="重置演示数据" title="重置演示数据" @click="resetDemo">
          <template #icon><RotateCcw :size="15" /></template><span>重置</span>
        </a-button>
        <a-button v-if="service.mode === 'api'" class="header-secondary" aria-label="编辑档案" title="编辑档案" :disabled="!workspace" @click="openEdit">
          <template #icon><PencilLine :size="15" /></template><span>编辑档案</span>
        </a-button>
        <a-button v-if="service.mode === 'api'" class="header-secondary" aria-label="新建会话" title="新建会话" :disabled="!workspace" @click="openConversationCreator">
          <template #icon><MessageCirclePlus :size="15" /></template><span>新建会话</span>
        </a-button>
        <a-button type="primary" aria-label="上传谈话记录" title="上传谈话记录" :disabled="!workspace" @click="uploadOpen = true">
          <template #icon><FileUp :size="15" /></template><span>上传谈话记录</span>
        </a-button>
        <a-button aria-label="打开档案助手" title="打开档案助手" :disabled="!workspace" @click="assistantOpen = true">
          <template #icon><Bot :size="15" /></template><span>助手</span>
        </a-button>
      </template>
    </PageHeader>

    <main class="workspace-content">
      <a-alert
        v-if="service.mode === 'demo'"
        type="warning"
        show-icon
        message="演示数据 · 不是生产档案"
        description="本工作台用于设计评审与交互验收；AI 摘要、风险识别和归档结果均为模拟状态。"
      />
      <a-alert v-if="error" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="loadWorkspace()">重试</a-button></template>
      </a-alert>
      <a-skeleton v-if="loading" active :paragraph="{ rows: 8 }" />

      <template v-else-if="workspace">
        <section class="student-hero">
          <div class="student-primary">
            <div class="student-name-row">
              <span class="student-avatar">{{ workspace.student.name.slice(0, 1) }}</span>
              <div>
                <div class="name-line">
                  <h2>{{ workspace.student.name }}</h2>
                  <span>{{ workspace.student.code }}</span>
                  <RiskTag :level="workspace.student.riskLevel" />
                </div>
                <p>{{ workspace.student.chiefConcern }}</p>
              </div>
            </div>
            <div class="hero-meta">
              <div><span>辅导进度</span><strong>第 {{ workspace.student.sessionCount }} 次</strong></div>
              <div><span>负责人</span><strong>{{ workspace.student.counselor }}</strong></div>
              <div><span>下次预约</span><strong>{{ service.mode === 'api' ? '后端能力尚未接入' : workspace.student.nextAppointment || '暂无安排' }}</strong></div>
              <div><span>最近动态</span><strong>{{ workspace.student.recentActivity }}</strong></div>
            </div>
          </div>
          <button type="button" class="next-session" aria-label="打开下一步助手" @click="assistantOpen = true">
            <CalendarClock :size="20" />
            <div><span>下一步助手</span><strong>{{ workspace.todos.find((item) => item.status === 'todo')?.title || '回顾当前阶段' }}</strong><small>查看推荐话题或自己定义</small></div>
          </button>
        </section>

        <nav class="workspace-tabs" aria-label="档案工作台标签">
          <button
            v-for="item in tabItems"
            :key="item.key"
            type="button"
            :class="{ active: activeTab === item.key }"
            @click="setTab(item.key)"
          >
            <component :is="item.icon" :size="17" />{{ item.label }}
            <span v-if="item.key === 'crisis' && workspace.crises.length">{{ workspace.crises.length }}</span>
          </button>
        </nav>

        <section v-if="activeTab === 'overview'" class="workspace-grid overview-grid">
          <article class="panel background-panel">
            <div class="panel-heading"><div><span>学生背景</span><h3>当前理解</h3></div></div>
            <p class="large-copy">{{ workspace.background }}</p>
            <div class="quick-actions">
              <button type="button" @click="uploadOpen = true"><FileUp :size="18" /><span><strong>上传记录</strong><small>生成可审阅摘要</small></span></button>
              <button type="button" @click="assistantOpen = true"><Bot :size="18" /><span><strong>下一步助手</strong><small>选择推荐或自定义话题</small></span></button>
              <button type="button" @click="setTab('timeline')"><History :size="18" /><span><strong>查看变化</strong><small>回顾历次辅导</small></span></button>
            </div>
          </article>
          <article class="panel">
            <div class="panel-heading"><div><span>本次待办</span><h3>需要继续跟进</h3></div><ListChecks :size="20" /></div>
            <a-alert v-if="service.mode === 'api'" type="info" show-icon message="待办能力尚未接入后端" />
            <a-empty v-else-if="!workspace.todos.length" description="当前没有待办" :image="null" />
            <ul v-else class="todo-list">
              <li v-for="item in workspace.todos" :key="item.id">
                <CheckCircle2 :size="18" :class="{ done: item.status === 'done' }" />
                <div><strong>{{ item.title }}</strong><span>{{ item.dueAt || '下次谈话前' }}</span></div>
              </li>
            </ul>
          </article>
          <article class="panel recent-panel">
            <div class="panel-heading"><div><span>最近动态</span><h3>档案发生了什么</h3></div></div>
            <div v-if="workspace.timeline[0]" class="recent-event">
              <span>{{ workspace.timeline[0].occurredAt }}</span>
              <strong>{{ workspace.timeline[0].title }}</strong>
              <p>{{ workspace.timeline[0].summary }}</p>
            </div>
            <a-empty v-else description="暂无动态" :image="null" />
          </article>
        </section>

        <section v-else-if="activeTab === 'timeline'" class="panel section-panel">
          <div class="panel-heading"><div><span>COUNSELING HISTORY</span><h3>辅导时间轴与前后变化</h3></div><a-button @click="uploadOpen = true">上传新记录</a-button></div>
          <a-empty v-if="!workspace.timeline.length" description="暂无辅导记录" />
          <div v-else class="timeline-list">
            <article v-for="record in workspace.timeline" :key="record.id">
              <div class="timeline-mark"></div>
              <div class="timeline-card">
                <header><div><span>{{ record.occurredAt }}</span><h4>{{ record.title }}</h4></div><a-tag>{{ record.source === 'upload' ? '文件归档' : '手动记录' }}</a-tag></header>
                <p>{{ record.summary }}</p>
                <a-button v-if="service.mode === 'api'" size="small" @click="router.push({ name: 'AgentCompWithThreadId', params: { thread_id: record.id }, query: { student_id: studentId } })">重开关联会话</a-button>
                <div v-if="record.moodBefore != null" class="mood-change">
                  <span>谈话前 {{ record.moodBefore }}</span><i>→</i><span>谈话后 {{ record.moodAfter }}</span>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section v-else-if="activeTab === 'goals'" class="panel section-panel">
          <div class="panel-heading"><div><span>ACTION & PRACTICE</span><h3>目标与家庭作业</h3></div></div>
          <a-alert v-if="service.mode === 'api'" type="info" show-icon message="目标与作业能力尚未接入后端" />
          <a-empty v-else-if="!workspace.goals.length" description="暂无目标" />
          <div v-else class="goal-grid">
            <article v-for="goal in workspace.goals" :key="goal.id">
              <header><Target :size="18" /><strong>{{ goal.title }}</strong><a-tag :color="goal.status === 'done' ? 'green' : 'blue'">{{ goal.status === 'done' ? '已完成' : '进行中' }}</a-tag></header>
              <a-progress :percent="goal.progress" :stroke-color="'var(--main-600)'" />
              <div><span>本次作业</span><p>{{ goal.homework || '暂未安排' }}</p></div>
            </article>
          </div>
        </section>

        <section v-else-if="activeTab === 'assessments'" class="workspace-grid assessment-grid">
          <article class="panel">
            <div class="panel-heading"><div><span>ASSESSMENT TREND</span><h3>量表与主观观察趋势</h3></div></div>
            <a-alert v-if="service.mode === 'api'" type="info" show-icon message="量表能力尚未接入后端" />
            <AssessmentTrend v-else :series="workspace.assessments" />
          </article>
          <article class="panel interpretation-panel">
            <div class="panel-heading"><div><span>解释</span><h3>人工阅读提示</h3></div></div>
            <a-alert v-if="service.mode === 'api'" type="info" show-icon message="暂无可读取的量表解释接口" />
            <a-empty v-else-if="!workspace.assessments.length" description="暂无解释" :image="null" />
            <div v-for="series in workspace.assessments" v-else :key="series.name" class="interpretation">
              <strong>{{ series.name }}</strong><p>{{ series.interpretation }}</p>
            </div>
          </article>
        </section>

        <section v-else class="panel section-panel crisis-panel">
          <div class="panel-heading"><div><span>RISK REVIEW</span><h3>危机与持续观察</h3></div><ShieldAlert :size="22" /></div>
          <a-alert
            v-if="service.mode === 'api'"
            type="info"
            show-icon
            message="后端风险评估能力尚未接入"
            description="当前页面不会把缺失的风险数据解释为低风险，也不提供自动危机判断。"
          />
          <a-alert v-else type="info" show-icon message="记录不等于处置" description="这里呈现人工复核后的风险观察；前端不会自动执行干预或宣称处置已经完成。" />
          <a-empty v-if="service.mode !== 'api' && !workspace.crises.length" description="暂无危机记录" />
          <div v-if="service.mode !== 'api' && workspace.crises.length" class="crisis-list">
            <article v-for="event in workspace.crises" :key="event.id">
              <header><RiskTag :level="event.level" /><span>{{ event.occurredAt }}</span><a-tag>{{ event.status === 'closed' ? '已关闭' : '观察中' }}</a-tag></header>
              <div><span>观察信号</span><p>{{ event.signal }}</p></div>
              <div><span>已记录响应</span><p>{{ event.response }}</p></div>
            </article>
          </div>
        </section>
      </template>
    </main>

    <a-modal v-model:open="editOpen" title="编辑档案" :confirm-loading="editBusy" @ok="saveEdit">
      <a-form layout="vertical">
        <a-form-item label="背景与主诉"><a-textarea v-model:value="editForm.chiefConcern" :rows="6" /></a-form-item>
        <a-form-item label="状态">
          <a-select v-model:value="editForm.status">
            <a-select-option value="active">辅导中</a-select-option>
            <a-select-option value="closed">阶段结束</a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="conversationOpen" title="新建辅导会话" :confirm-loading="conversationBusy" @ok="createConversation">
      <a-alert v-if="conversationError" type="error" show-icon :message="conversationError" class="conversation-alert" />
      <a-form layout="vertical">
        <a-form-item label="背景快照">
          <a-textarea :value="workspace?.background" :rows="4" disabled />
        </a-form-item>
        <a-form-item label="智能体" required>
          <a-select v-model:value="conversationForm.agent_id" placeholder="选择智能体">
            <a-select-option v-for="item in availableAgents" :key="item.id" :value="item.id">{{ item.name }}</a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <RecordUploadFlow
      v-if="studentId"
      :open="uploadOpen"
      :student-id="studentId"
      :service="service"
      :thread-id="service.mode === 'api' ? String(workspace?.timeline?.[0]?.id || '') : ''"
      @close="uploadOpen = false"
      @archived="handleArchived"
    />
    <CounselingAssistantDrawer
      :open="assistantOpen"
      :student="workspace?.student"
      :messages="workspace?.assistantMessages || []"
      :busy="assistantBusy"
      :mode="service.mode"
      @close="assistantOpen = false"
      :next-step-topics="nextStepTopics"
      @send="sendAssistant"
    />
  </div>
</template>

<style scoped>
.conversation-alert { margin-bottom: 14px; }
.workspace-page { min-height: 100%; color: var(--gray-900); background: var(--gray-25); }
.workspace-content { display: grid; gap: 18px; max-width: 1320px; margin: 0 auto; padding: 22px var(--page-padding) 48px; }
.student-hero { display: grid; grid-template-columns: 1fr minmax(260px, 32%); gap: 14px; }
.student-primary, .next-session { border: 1px solid var(--gray-150); border-radius: 17px; background: var(--gray-0); }
.student-primary { padding: 22px; }
.student-name-row, .name-line, .next-session, .panel-heading, .quick-actions button, .goal-grid header, .crisis-list header { display: flex; align-items: center; }
.student-name-row { gap: 14px; }
.student-avatar { display: grid; place-items: center; flex: 0 0 48px; height: 48px; border-radius: 15px; color: var(--main-800); background: var(--main-50); font-size: 20px; font-weight: 800; }
.name-line { gap: 9px; flex-wrap: wrap; }
.name-line h2 { margin: 0; color: var(--gray-1000); font-size: 22px; }
.name-line > span { color: var(--gray-500); font-size: 12px; }
.student-name-row p { margin: 5px 0 0; color: var(--gray-600); }
.hero-meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 20px; padding-top: 17px; border-top: 1px solid var(--gray-100); }
.hero-meta div { display: grid; gap: 4px; min-width: 0; }
.hero-meta span, .panel-heading span, .next-session span { color: var(--gray-500); font-size: 11px; }
.hero-meta strong { overflow: hidden; color: var(--gray-800); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.next-session { gap: 12px; width: 100%; padding: 20px; color: var(--second-700); background: linear-gradient(140deg, var(--second-30), var(--gray-0)); text-align: left; cursor: pointer; }
.next-session:hover { border-color: var(--second-300); background: var(--second-30); }
.next-session div { display: grid; gap: 5px; }
.next-session strong { color: var(--gray-900); line-height: 1.45; }
.next-session small { color: var(--gray-500); font-size: 11px; }
.workspace-tabs { display: flex; gap: 4px; padding: 5px; overflow-x: auto; border: 1px solid var(--gray-150); border-radius: 13px; background: var(--gray-0); }
.workspace-tabs button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; flex: 1; min-width: 120px; padding: 10px 14px; border: 0; border-radius: 9px; color: var(--gray-600); background: transparent; cursor: pointer; white-space: nowrap; }
.workspace-tabs button.active { color: var(--main-800); background: var(--main-50); font-weight: 700; }
.workspace-tabs button > span { display: grid; place-items: center; min-width: 19px; height: 19px; border-radius: 10px; color: var(--gray-0); background: var(--color-error-500); font-size: 10px; }
.workspace-grid { display: grid; gap: 14px; }
.overview-grid { grid-template-columns: 1.45fr 1fr; }
.panel { padding: 20px; border: 1px solid var(--gray-150); border-radius: 16px; background: var(--gray-0); }
.panel-heading { justify-content: space-between; gap: 12px; margin-bottom: 17px; }
.panel-heading h3 { margin: 4px 0 0; color: var(--gray-1000); font-size: 17px; }
.panel-heading > svg { color: var(--main-600); }
.large-copy { margin: 0; color: var(--gray-700); font-size: 15px; line-height: 1.8; }
.quick-actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; margin-top: 22px; }
.quick-actions button { gap: 9px; padding: 12px; border: 1px solid var(--gray-150); border-radius: 10px; color: var(--main-700); background: var(--gray-25); text-align: left; cursor: pointer; }
.quick-actions button span { display: grid; gap: 2px; }
.quick-actions strong { color: var(--gray-800); font-size: 13px; }
.quick-actions small { color: var(--gray-500); font-size: 10px; }
.todo-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.todo-list li { display: flex; align-items: flex-start; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--gray-100); }
.todo-list svg { color: var(--gray-300); }
.todo-list svg.done { color: var(--color-success-500); }
.todo-list div { display: grid; gap: 4px; }
.todo-list strong { color: var(--gray-800); font-size: 13px; }
.todo-list span { color: var(--gray-500); font-size: 11px; }
.recent-panel { grid-column: 1 / -1; }
.recent-event { display: grid; gap: 6px; padding-left: 14px; border-left: 3px solid var(--main-300); }
.recent-event span { color: var(--gray-500); font-size: 11px; }
.recent-event p { margin: 0; color: var(--gray-600); }
.section-panel { min-height: 360px; }
.timeline-list { display: grid; padding-left: 13px; }
.timeline-list > article { display: grid; grid-template-columns: 20px 1fr; }
.timeline-mark { position: relative; border-left: 1px solid var(--gray-200); }
.timeline-mark::before { content: ''; position: absolute; left: -5px; top: 22px; width: 9px; height: 9px; border: 2px solid var(--gray-0); border-radius: 50%; background: var(--main-500); box-shadow: 0 0 0 2px var(--main-100); }
.timeline-card { margin-bottom: 14px; padding: 16px; border: 1px solid var(--gray-150); border-radius: 12px; background: var(--gray-25); }
.timeline-card header { display: flex; justify-content: space-between; gap: 12px; }
.timeline-card header span { color: var(--gray-500); font-size: 11px; }
.timeline-card h4 { margin: 4px 0 0; color: var(--gray-900); }
.timeline-card p { color: var(--gray-600); line-height: 1.65; }
.mood-change { display: inline-flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 8px; color: var(--gray-700); background: var(--gray-0); font-size: 12px; }
.mood-change i { color: var(--main-600); font-style: normal; }
.goal-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.goal-grid article { padding: 17px; border: 1px solid var(--gray-150); border-radius: 12px; background: var(--gray-25); }
.goal-grid header { gap: 9px; }
.goal-grid header strong { flex: 1; color: var(--gray-900); }
.goal-grid article > div { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--gray-150); }
.goal-grid span, .crisis-list div > span { color: var(--gray-500); font-size: 11px; }
.goal-grid p, .crisis-list p { margin: 4px 0 0; color: var(--gray-700); }
.assessment-grid { grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); }
.interpretation { padding: 13px 0; border-bottom: 1px solid var(--gray-100); }
.interpretation p { margin: 5px 0 0; color: var(--gray-600); line-height: 1.55; }
.crisis-panel { display: grid; gap: 16px; }
.crisis-list { display: grid; gap: 12px; }
.crisis-list article { display: grid; gap: 13px; padding: 16px; border: 1px solid var(--gray-150); border-left: 3px solid var(--color-warning-500); border-radius: 11px; background: var(--gray-25); }
.crisis-list header { gap: 9px; }
.crisis-list header > span { flex: 1; color: var(--gray-500); font-size: 12px; }
@media (max-width: 1024px) {
  .student-hero, .assessment-grid { grid-template-columns: 1fr; }
  .hero-meta { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .workspace-content { padding-top: 15px; }
  .overview-grid { grid-template-columns: 1fr; }
  .recent-panel { grid-column: auto; }
  .goal-grid { grid-template-columns: 1fr; }
  .quick-actions { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .workspace-content { padding-inline: 12px; }
  .student-primary, .panel { padding: 16px; }
  .hero-meta { grid-template-columns: 1fr 1fr; }
  :deep(.page-header-right .ant-tag) { display: none; }
  :deep(.page-header-title) { max-width: 92px; overflow: hidden; text-overflow: ellipsis; }
  :deep(.page-header-right) { gap: 4px; }
  :deep(.page-header-right .ant-btn) { width: 30px; padding-inline: 6px; font-size: 0; }
  :deep(.page-header-right .ant-btn-icon) { margin-inline-end: 0; }
  .workspace-tabs { margin-inline: -12px; border-radius: 0; border-inline: 0; }
  .workspace-tabs button { flex: 0 0 auto; min-width: auto; padding-inline: 13px; }
  .workspace-tabs button svg { display: none; }
}
</style>
