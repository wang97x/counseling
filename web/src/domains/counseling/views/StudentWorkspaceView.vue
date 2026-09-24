<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, CheckCircle2, ClipboardPenLine, FileClock,
  History, PencilLine, ShieldAlert, UserRoundCheck,
} from '@lucide/vue'
import { message } from 'ant-design-vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import RiskTag from '../components/RiskTag.vue'
import { counselingWorkspaceService } from '../workspaceService.js'
import { createLatestOperation, isCurrentStudentRequest } from '../requestGuard.js'

const route = useRoute()
const router = useRouter()
const service = counselingWorkspaceService
const workspace = ref(null)
const loading = ref(false)
const error = ref('')
const editOpen = ref(false)
const recordOpen = ref(false)
const riskOpen = ref(false)
const correctionOpen = ref(false)
const closeOpen = ref(false)
const busy = ref(false)
const editForm = reactive({ displayName: '', className: '', chiefConcern: '' })
const recordForm = reactive(emptyRecordForm())
const riskForm = reactive({ level: 'watch', basis: '', actionTaken: '', status: 'monitoring' })
const correctionForm = reactive({ recordId: '', reason: '', ...emptyContent() })
const closeForm = reactive({ closureNote: '' })
const studentId = computed(() => String(route.params.studentId || ''))
const activeDrafts = computed(() => workspace.value?.drafts || [])
const operations = createLatestOperation()
let requestVersion = 0

function emptyContent() {
  return { overview: '', observation: '', actionTaken: '', nextPlan: '', riskNotes: '' }
}

function localDateTimeValue(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function emptyRecordForm() {
  return {
    id: '', version: 0, consultedAt: localDateTimeValue(), consultationType: '面谈', ...emptyContent(),
  }
}

function contentPayload(form) {
  return {
    overview: form.overview.trim(),
    observation: form.observation.trim(),
    action_taken: form.actionTaken.trim(),
    next_plan: form.nextPlan.trim(),
    risk_notes: form.riskNotes.trim(),
  }
}

async function loadWorkspace(id = studentId.value) {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
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

function openEdit() {
  Object.assign(editForm, {
    displayName: workspace.value.student.name.startsWith('学生 ') ? '' : workspace.value.student.name,
    className: workspace.value.student.className,
    chiefConcern: workspace.value.background === '尚未录入背景信息' ? '' : workspace.value.background,
  })
  editOpen.value = true
}

async function saveEdit() {
  await runAction(async () => {
    await service.updateStudent(studentId.value, { ...editForm })
    editOpen.value = false
    await loadWorkspace()
    message.success('档案信息已保存')
  }, '保存档案失败')
}

function openNewRecord() {
  Object.assign(recordForm, emptyRecordForm())
  recordOpen.value = true
}

function openDraft(draft) {
  const content = draft.content || {}
  Object.assign(recordForm, {
    id: draft.id,
    version: draft.version,
    consultedAt: localDateTimeValue(draft.consultedAt),
    consultationType: draft.consultationType || '面谈',
    overview: content.overview || '',
    observation: content.observation || '',
    actionTaken: content.action_taken || '',
    nextPlan: content.next_plan || '',
    riskNotes: content.risk_notes || '',
  })
  recordOpen.value = true
}

async function persistRecordDraft() {
  if (!recordForm.overview.trim()) throw new Error('请填写本次咨询概述')
  if (!recordForm.consultedAt) throw new Error('请选择咨询时间')
  const payload = {
    consulted_at: new Date(recordForm.consultedAt).toISOString(),
    consultation_type: recordForm.consultationType,
    content: contentPayload(recordForm),
  }
  const result = recordForm.id
    ? await service.updateManualRecordDraft(studentId.value, recordForm.id, {
      ...payload, expected_version: recordForm.version,
    })
    : await service.createManualRecordDraft(studentId.value, {
      ...payload, request_id: crypto.randomUUID(),
    })
  Object.assign(recordForm, { id: result.data.id, version: result.data.version })
  return result.data
}

async function saveRecordDraft() {
  await runAction(async () => {
    await persistRecordDraft()
    recordOpen.value = false
    await loadWorkspace()
    message.success('咨询记录草稿已保存')
  }, '保存咨询记录失败')
}

async function confirmRecord() {
  await runAction(async () => {
    const draft = await persistRecordDraft()
    await service.confirmManualRecord(studentId.value, draft.id, draft.version, crypto.randomUUID())
    recordOpen.value = false
    await loadWorkspace()
    message.success('咨询记录已由你确认并归档')
  }, '确认归档失败')
}

function openCorrection(item) {
  const content = item.content || {}
  Object.assign(correctionForm, {
    recordId: item.id,
    reason: '',
    overview: content.overview || '',
    observation: content.observation || '',
    actionTaken: content.action_taken || '',
    nextPlan: content.next_plan || '',
    riskNotes: content.risk_notes || '',
  })
  correctionOpen.value = true
}

async function saveCorrection() {
  if (!correctionForm.reason.trim()) return message.error('请填写更正原因')
  await runAction(async () => {
    await service.addRecordCorrection(studentId.value, correctionForm.recordId, {
      request_id: crypto.randomUUID(),
      reason: correctionForm.reason.trim(),
      corrected_content: contentPayload(correctionForm),
    })
    correctionOpen.value = false
    await loadWorkspace()
    message.success('更正已追加，原记录保持不变')
  }, '追加更正失败')
}

function openRisk() {
  Object.assign(riskForm, { level: 'watch', basis: '', actionTaken: '', status: 'monitoring' })
  riskOpen.value = true
}

async function saveRisk() {
  if (!riskForm.basis.trim()) return message.error('请填写人工判断依据')
  await runAction(async () => {
    await service.createRiskEvent(studentId.value, {
      request_id: crypto.randomUUID(),
      level: riskForm.level,
      basis: riskForm.basis.trim(),
      action_taken: riskForm.actionTaken.trim(),
      status: riskForm.status,
      source_record_id: null,
    })
    riskOpen.value = false
    await loadWorkspace()
    message.success('人工风险记录已保存')
  }, '保存风险记录失败')
}

function openClose() {
  closeForm.closureNote = ''
  closeOpen.value = true
}

async function closeStudent() {
  if (!closeForm.closureNote.trim()) return message.error('请填写阶段结束说明')
  await runAction(async () => {
    await service.closeStudent(studentId.value, workspace.value.student.version, closeForm.closureNote.trim())
    closeOpen.value = false
    await loadWorkspace()
    message.success('当前辅导阶段已结束')
  }, '结束阶段失败')
}

async function runAction(action, fallback) {
  const id = studentId.value
  const version = requestVersion
  const operation = operations.begin()
  busy.value = true
  try {
    await action()
  } catch (cause) {
    if (isCurrentStudentRequest(id, version, studentId.value, requestVersion) && operations.isCurrent(operation)) {
      message.error(cause.message || fallback)
    }
  } finally {
    if (operations.isCurrent(operation)) busy.value = false
  }
}

function timelineLabel(item) {
  return {
    consultation_record: '正式咨询记录',
    record_correction: '追加更正',
    risk_event: '人工风险记录',
    record: '文件记录',
    conversation: '历史会话',
  }[item.type] || '档案记录'
}

watch(studentId, (id) => {
  operations.invalidate()
  for (const modal of [editOpen, recordOpen, riskOpen, correctionOpen, closeOpen]) modal.value = false
  busy.value = false
  workspace.value = null
  if (id) void loadWorkspace(id)
}, { immediate: true })
</script>

<template>
  <div class="workspace-page">
    <PageHeader :title="workspace?.student?.name ? workspace.student.name + '的档案' : '档案工作台'" :loading="loading" :show-border="true">
      <template #actions>
        <a-button aria-label="返回档案列表" @click="router.push('/students')"><ArrowLeft :size="15" />返回列表</a-button>
        <a-button :disabled="!workspace" @click="openEdit"><PencilLine :size="15" />编辑信息</a-button>
        <a-button v-if="workspace?.student?.status !== 'closed'" type="primary" :disabled="!workspace" @click="openNewRecord">
          <ClipboardPenLine :size="15" />新增咨询记录
        </a-button>
      </template>
    </PageHeader>

    <main class="workspace-content">
      <a-alert v-if="error" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="loadWorkspace()">重试</a-button></template>
      </a-alert>
      <a-skeleton v-if="loading" active :paragraph="{ rows: 8 }" />

      <template v-else-if="workspace">
        <section class="student-card">
          <div class="student-heading">
            <span class="student-avatar"><UserRoundCheck :size="24" /></span>
            <div>
              <div class="name-line">
                <h2>{{ workspace.student.name }}</h2>
                <span>{{ workspace.student.code }}</span>
                <a-tag :color="workspace.student.status === 'closed' ? 'default' : 'blue'">
                  {{ workspace.student.status === 'closed' ? '阶段结束' : '辅导中' }}
                </a-tag>
                <RiskTag :level="workspace.student.riskLevel" />
              </div>
              <p>{{ workspace.student.className || '未填写班级' }} · 负责人 {{ workspace.student.counselor }}</p>
            </div>
          </div>
          <div class="background-copy">
            <span>背景与主诉</span>
            <p>{{ workspace.background }}</p>
          </div>
          <div class="business-actions">
            <a-button @click="openRisk"><ShieldAlert :size="15" />记录人工风险</a-button>
            <a-button v-if="workspace.student.status !== 'closed'" danger @click="openClose"><CheckCircle2 :size="15" />结束当前阶段</a-button>
          </div>
          <a-alert
            v-if="workspace.student.status === 'closed'"
            type="success"
            show-icon
            message="当前辅导阶段已结束"
            :description="workspace.student.closureNote || '未填写结束说明'"
          />
        </section>

        <section v-if="activeDrafts.length" class="panel">
          <div class="section-heading">
            <div><span>待确认</span><h3>咨询记录草稿</h3></div>
            <FileClock :size="21" />
          </div>
          <div class="draft-list">
            <button v-for="draft in activeDrafts" :key="draft.id" type="button" @click="openDraft(draft)">
              <div><strong>{{ draft.consultationType || '咨询' }}草稿</strong><span>{{ draft.consultedAt }}</span></div>
              <p>{{ draft.content?.overview || '尚未填写概述' }}</p>
              <span>继续填写并确认</span>
            </button>
          </div>
        </section>

        <section class="panel timeline-panel">
          <div class="section-heading">
            <div><span>完整历史</span><h3>统一时间线</h3></div>
            <History :size="21" />
          </div>
          <a-empty v-if="!workspace.timeline.length" description="暂无已确认的档案记录" />
          <div v-else class="timeline-list">
            <article v-for="item in workspace.timeline" :key="item.type + '-' + item.id">
              <span class="timeline-dot"></span>
              <div class="timeline-body">
                <header>
                  <div><span>{{ item.occurredAt }}</span><h4>{{ item.title }}</h4></div>
                  <a-tag>{{ timelineLabel(item) }}</a-tag>
                </header>
                <p class="timeline-summary">{{ item.summary }}</p>
                <dl v-if="item.content" class="record-details">
                  <template v-if="item.content.observation"><dt>观察</dt><dd>{{ item.content.observation }}</dd></template>
                  <template v-if="item.content.action_taken"><dt>已采取行动</dt><dd>{{ item.content.action_taken }}</dd></template>
                  <template v-if="item.content.next_plan"><dt>后续计划</dt><dd>{{ item.content.next_plan }}</dd></template>
                  <template v-if="item.content.risk_notes"><dt>风险备注</dt><dd>{{ item.content.risk_notes }}</dd></template>
                </dl>
                <div v-if="item.type === 'risk_event'" class="risk-line">
                  <RiskTag :level="item.riskLevel" /><span>{{ item.riskStatus === 'closed' ? '已关闭' : '持续跟进' }}</span>
                </div>
                <a-button v-if="item.type === 'consultation_record'" size="small" @click="openCorrection(item)">
                  追加更正
                </a-button>
              </div>
            </article>
          </div>
        </section>
      </template>
    </main>

    <a-modal v-model:open="editOpen" title="编辑学生信息" :confirm-loading="busy" @ok="saveEdit">
      <a-form layout="vertical">
        <a-form-item label="显示名称"><a-input v-model:value="editForm.displayName" maxlength="128" /></a-form-item>
        <a-form-item label="班级"><a-input v-model:value="editForm.className" maxlength="128" /></a-form-item>
        <a-form-item label="背景与主诉"><a-textarea v-model:value="editForm.chiefConcern" :rows="6" maxlength="10000" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="recordOpen" title="手工咨询记录" :confirm-loading="busy" :mask-closable="false" width="720px">
      <a-alert type="info" show-icon message="保存草稿不会进入正式时间线；确认归档后原记录不可修改，只能追加更正。" />
      <a-form layout="vertical" class="modal-form">
        <div class="form-row">
          <a-form-item label="咨询时间" required><a-input v-model:value="recordForm.consultedAt" type="datetime-local" /></a-form-item>
          <a-form-item label="咨询方式" required><a-select v-model:value="recordForm.consultationType"><a-select-option value="面谈">面谈</a-select-option><a-select-option value="电话">电话</a-select-option><a-select-option value="线上">线上</a-select-option><a-select-option value="其他">其他</a-select-option></a-select></a-form-item>
        </div>
        <a-form-item label="本次咨询概述" required><a-textarea v-model:value="recordForm.overview" :rows="4" maxlength="10000" /></a-form-item>
        <a-form-item label="辅导员观察"><a-textarea v-model:value="recordForm.observation" :rows="3" maxlength="10000" /></a-form-item>
        <a-form-item label="已采取行动"><a-textarea v-model:value="recordForm.actionTaken" :rows="3" maxlength="10000" /></a-form-item>
        <a-form-item label="后续计划"><a-textarea v-model:value="recordForm.nextPlan" :rows="3" maxlength="10000" /></a-form-item>
        <a-form-item label="风险备注（不自动改变风险等级）"><a-textarea v-model:value="recordForm.riskNotes" :rows="2" maxlength="10000" /></a-form-item>
      </a-form>
      <template #footer>
        <a-button @click="recordOpen = false">取消</a-button>
        <a-button :loading="busy" @click="saveRecordDraft">保存草稿</a-button>
        <a-button type="primary" :loading="busy" @click="confirmRecord">确认并归档</a-button>
      </template>
    </a-modal>

    <a-modal v-model:open="correctionOpen" title="追加正式记录更正" :confirm-loading="busy" width="680px" @ok="saveCorrection">
      <a-alert type="warning" show-icon message="更正会作为新事件追加，原正式记录不会被覆盖。" />
      <a-form layout="vertical" class="modal-form">
        <a-form-item label="更正原因" required><a-textarea v-model:value="correctionForm.reason" :rows="2" maxlength="2000" /></a-form-item>
        <a-form-item label="更正后的咨询概述" required><a-textarea v-model:value="correctionForm.overview" :rows="4" /></a-form-item>
        <a-form-item label="辅导员观察"><a-textarea v-model:value="correctionForm.observation" :rows="2" /></a-form-item>
        <a-form-item label="已采取行动"><a-textarea v-model:value="correctionForm.actionTaken" :rows="2" /></a-form-item>
        <a-form-item label="后续计划"><a-textarea v-model:value="correctionForm.nextPlan" :rows="2" /></a-form-item>
        <a-form-item label="风险备注"><a-textarea v-model:value="correctionForm.riskNotes" :rows="2" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="riskOpen" title="记录人工风险判断" :confirm-loading="busy" @ok="saveRisk">
      <a-alert type="info" show-icon message="风险等级由辅导员人工判断；系统不会依据正文自动判断或执行危机干预。" />
      <a-form layout="vertical" class="modal-form">
        <div class="form-row">
          <a-form-item label="风险等级" required><a-select v-model:value="riskForm.level"><a-select-option value="normal">常规关注</a-select-option><a-select-option value="watch">持续观察</a-select-option><a-select-option value="urgent">紧急关注</a-select-option></a-select></a-form-item>
          <a-form-item label="跟进状态" required><a-select v-model:value="riskForm.status"><a-select-option value="open">待跟进</a-select-option><a-select-option value="monitoring">持续跟进</a-select-option><a-select-option value="closed">本事件已关闭</a-select-option></a-select></a-form-item>
        </div>
        <a-form-item label="人工判断依据" required><a-textarea v-model:value="riskForm.basis" :rows="4" maxlength="10000" /></a-form-item>
        <a-form-item label="已采取行动"><a-textarea v-model:value="riskForm.actionTaken" :rows="3" maxlength="10000" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="closeOpen" title="结束当前辅导阶段" :confirm-loading="busy" ok-text="确认结束" ok-type="danger" @ok="closeStudent">
      <a-alert type="warning" show-icon message="阶段结束不代表风险自动解除，历史记录仍会保留。" />
      <a-form layout="vertical" class="modal-form">
        <a-form-item label="阶段结束说明" required><a-textarea v-model:value="closeForm.closureNote" :rows="5" maxlength="10000" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style scoped>
.workspace-page { min-height: 100%; color: var(--gray-900); background: var(--gray-25); }
.workspace-content { display: grid; gap: 18px; max-width: 1120px; margin: 0 auto; padding: 22px var(--page-padding) 48px; }
.student-card, .panel { padding: 22px; border: 1px solid var(--gray-150); border-radius: 16px; background: var(--gray-0); }
.student-card { display: grid; gap: 20px; }
.student-heading, .name-line, .business-actions, .section-heading, .timeline-body header, .risk-line { display: flex; align-items: center; }
.student-heading { gap: 14px; }
.student-avatar { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 14px; color: var(--main-700); background: var(--main-50); }
.name-line { gap: 9px; flex-wrap: wrap; }
.name-line h2 { margin: 0; font-size: 22px; }
.name-line > span, .student-heading p, .section-heading span, .timeline-body header span { color: var(--gray-500); font-size: 12px; }
.student-heading p { margin: 5px 0 0; }
.background-copy { padding: 16px; border-radius: 12px; background: var(--gray-50); }
.background-copy > span { color: var(--gray-500); font-size: 12px; }
.background-copy p { margin: 7px 0 0; white-space: pre-wrap; line-height: 1.7; }
.business-actions { gap: 10px; flex-wrap: wrap; }
.section-heading { justify-content: space-between; margin-bottom: 16px; }
.section-heading h3 { margin: 4px 0 0; font-size: 18px; }
.section-heading > svg { color: var(--main-600); }
.draft-list { display: grid; gap: 10px; }
.draft-list button { display: grid; gap: 7px; padding: 14px; border: 1px solid var(--gray-150); border-radius: 11px; background: var(--gray-0); text-align: left; cursor: pointer; }
.draft-list button:hover { border-color: var(--main-300); background: var(--main-30); }
.draft-list button div { display: flex; justify-content: space-between; gap: 12px; }
.draft-list p { margin: 0; color: var(--gray-700); }
.draft-list button > span, .draft-list button div span { color: var(--main-700); font-size: 12px; }
.timeline-list { display: grid; gap: 0; }
.timeline-list article { position: relative; display: grid; grid-template-columns: 22px 1fr; gap: 12px; padding-bottom: 20px; }
.timeline-list article:not(:last-child)::before { position: absolute; top: 16px; bottom: 0; left: 6px; width: 1px; background: var(--gray-200); content: ''; }
.timeline-dot { z-index: 1; width: 13px; height: 13px; margin-top: 6px; border: 3px solid var(--main-100); border-radius: 50%; background: var(--main-600); }
.timeline-body { display: grid; gap: 11px; padding: 16px; border: 1px solid var(--gray-150); border-radius: 12px; }
.timeline-body header { justify-content: space-between; gap: 12px; }
.timeline-body h4 { margin: 3px 0 0; }
.timeline-summary { margin: 0; white-space: pre-wrap; line-height: 1.65; }
.record-details { display: grid; grid-template-columns: 90px 1fr; gap: 7px 12px; margin: 0; padding-top: 10px; border-top: 1px solid var(--gray-100); }
.record-details dt { color: var(--gray-500); font-size: 12px; }
.record-details dd { margin: 0; white-space: pre-wrap; }
.risk-line { gap: 9px; color: var(--gray-600); font-size: 12px; }
.modal-form { margin-top: 18px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 640px) {
  .workspace-content { padding-inline: 14px; }
  .student-card, .panel { padding: 16px; }
  .form-row { grid-template-columns: 1fr; gap: 0; }
  .record-details { grid-template-columns: 1fr; }
}
</style>
