<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { AlertTriangle, CheckCircle2, FileText, UploadCloud } from '@lucide/vue'
import { processCounselingRecordUpload } from '../../services/counseling/recordUploadFlow.js'
import { createLatestOperation, isCurrentCounselingOperation } from '../../utils/counselingRequestGuard.js'

const props = defineProps({
  open: Boolean,
  studentId: { type: String, required: true },
  service: { type: Object, required: true },
  threadId: { type: String, default: '' },
})
const emit = defineEmits(['close', 'archived'])
const step = ref(0)
const busy = ref(false)
const error = ref('')
const uploaded = ref(null)
const draft = reactive({
  id: '', studentId: '', uploadId: '', emotion: '', coreIssue: '', pattern: '',
  riskAssessment: '', riskLevel: 'normal', homework: '', nextPlan: '',
})
const preview = ref(null)
const completionMode = ref('')
const riskAcknowledged = ref(false)
const fileInput = ref(null)
const serviceMode = computed(() => props.service.mode)
const flowOperations = createLatestOperation()
const steps = computed(() => serviceMode.value === 'api'
  ? ['上传记录', '附件已加入']
  : ['上传记录', '审阅摘要', '影响预览', '归档完成'])
const isHighRisk = computed(() => draft.riskLevel === 'high')

function reset() {
  flowOperations.invalidate()
  step.value = 0
  busy.value = false
  error.value = ''
  uploaded.value = null
  preview.value = null
  completionMode.value = ''
  riskAcknowledged.value = false
  Object.assign(draft, {
    id: '', studentId: '', uploadId: '', emotion: '', coreIssue: '', pattern: '',
    riskAssessment: '', riskLevel: 'normal', homework: '', nextPlan: '',
  })
}

watch(
  () => [props.open, props.studentId],
  ([open]) => {
    flowOperations.invalidate()
    if (open) reset()
    else busy.value = false
  },
)

function useResult(result) {
  if (result.status === 'not_supported') {
    error.value = result.message || '后端能力尚未接入'
    return false
  }
  if (result.status !== 'ok') {
    error.value = result.message || '操作失败，请重试'
    return false
  }
  return true
}

async function chooseFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const operation = flowOperations.begin()
  const requestStudentId = props.studentId
  busy.value = true
  error.value = ''
  try {
    const result = await processCounselingRecordUpload(
      props.service,
      requestStudentId,
      file,
      { threadId: props.threadId },
    )
    if (!isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) return
    if (!useResult(result)) return
    uploaded.value = result.uploaded
    if (result.kind === 'attachment_only') {
      completionMode.value = result.kind
      step.value = 1
      return
    }
    Object.assign(draft, result.draft)
    step.value = 1
  } catch (cause) {
    if (!isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) return
    error.value = cause.message || '解析文件失败'
  } finally {
    if (isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) {
      busy.value = false
    }
  }
}

async function reviewImpact() {
  const operation = flowOperations.begin()
  const requestStudentId = props.studentId
  busy.value = true
  error.value = ''
  try {
    const saved = await props.service.saveDraft(requestStudentId, { ...draft })
    if (!isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) return
    if (!useResult(saved)) return
    const result = await props.service.buildArchivePreview(requestStudentId, { ...draft })
    if (!isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) return
    if (!useResult(result)) return
    preview.value = result.data
    step.value = 2
  } catch (cause) {
    if (!isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) return
    error.value = cause.message || '生成归档影响失败'
  } finally {
    if (isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) {
      busy.value = false
    }
  }
}

async function archive() {
  const operation = flowOperations.begin()
  const requestStudentId = props.studentId
  busy.value = true
  error.value = ''
  try {
    const result = await props.service.archiveSummary(
      requestStudentId,
      { ...draft },
      { riskAcknowledged: riskAcknowledged.value },
    )
    if (!isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) return
    if (!useResult(result)) return
    completionMode.value = 'archived'
    step.value = 3
    emit('archived', result.data)
  } catch (cause) {
    if (!isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) return
    error.value = cause.message || '归档失败'
  } finally {
    if (isCurrentCounselingOperation(flowOperations, operation, requestStudentId, props.studentId, props.open)) {
      busy.value = false
    }
  }
}

const impactLabels = {
  timeline: '时间轴',
  goals: '目标与作业',
  assessments: '量表',
  crisis: '危机',
  todos: '待办',
}
</script>

<template>
  <a-modal
    :open="open"
    :width="760"
    :footer="null"
    :mask-closable="!busy"
    title="上传谈话记录"
    wrap-class-name="record-upload-modal"
    @cancel="emit('close')"
  >
    <div class="flow-shell">
      <a-steps :current="step" size="small" :items="steps.map((title) => ({ title }))" />
      <a-alert
        v-if="service.mode === 'demo'"
        type="warning"
        show-icon
        message="演示评审请勿上传或填写真实个人、健康或其他敏感信息"
        class="flow-alert"
      />
      <a-alert
        v-if="error"
        :type="error.includes('后端能力尚未接入') ? 'info' : 'error'"
        show-icon
        :message="error"
        class="flow-alert"
      />

      <section v-if="step === 0" class="upload-stage">
        <button type="button" class="drop-zone" :disabled="busy" @click="fileInput?.click()">
          <UploadCloud :size="34" />
          <strong>{{ busy ? '正在解析记录…' : '选择谈话记录' }}</strong>
          <span>支持 TXT、DOCX、PDF，最大 5 MB</span>
          <span v-if="service.mode === 'demo'" class="demo-copy">演示模式只保存文件名、大小和固定解析结果，不保存文件内容。</span>
          <span v-else class="demo-copy">文件将通过现有附件接口加入最近一次关联会话；AI 摘要与归档能力尚未接入。</span>
        </button>
        <input ref="fileInput" class="visually-hidden" type="file" accept=".txt,.docx,.pdf" @change="chooseFile" />
        <a-progress v-if="busy" :percent="72" status="active" :show-info="false" />
      </section>

      <section v-else-if="step === 1 && completionMode !== 'attachment_only'" class="draft-stage">
        <div class="source-file">
          <FileText :size="18" />
          <div><strong>{{ uploaded?.name }}</strong><span>{{ uploaded?.parsedPreview }}</span></div>
        </div>
        <a-alert
          v-if="isHighRisk"
          type="error"
          show-icon
          message="该摘要包含高风险内容"
          description="请逐项核对原始记录。本页面不会自动执行干预，也不代表危机处置已经完成。"
        />
        <div class="draft-grid">
          <label><span>情绪</span><a-textarea v-model:value="draft.emotion" :rows="3" /></label>
          <label><span>核心议题</span><a-textarea v-model:value="draft.coreIssue" :rows="3" /></label>
          <label><span>认知或行为模式</span><a-textarea v-model:value="draft.pattern" :rows="3" /></label>
          <label><span>风险评估</span><a-textarea v-model:value="draft.riskAssessment" :rows="3" /></label>
          <label><span>家庭作业</span><a-textarea v-model:value="draft.homework" :rows="3" /></label>
          <label><span>下次计划</span><a-textarea v-model:value="draft.nextPlan" :rows="3" /></label>
        </div>
        <div class="flow-actions">
          <a-button @click="reset">重新选择</a-button>
          <a-button type="primary" :loading="busy" @click="reviewImpact">检查归档影响</a-button>
        </div>
      </section>

      <section v-else-if="step === 2" class="preview-stage">
        <div>
          <span class="stage-kicker">归档影响预览</span>
          <h3>确认后将同步更新以下档案内容</h3>
          <p>这里只展示将发生的变化，确认前不会写入档案。</p>
        </div>
        <ul class="impact-list">
          <li v-for="impact in preview?.impacts" :key="impact.section">
            <span>{{ impactLabels[impact.section] }}</span>
            <div><strong>{{ impact.action === 'add' ? '新增' : '更新' }}</strong><p>{{ impact.description }}</p></div>
          </li>
        </ul>
        <div v-if="preview?.requiresRiskAcknowledgement" class="risk-confirm">
          <AlertTriangle :size="20" />
          <a-checkbox v-model:checked="riskAcknowledged">
            我已对照原始记录核对风险内容，并知晓归档不等于已完成危机处置
          </a-checkbox>
        </div>
        <div class="flow-actions">
          <a-button @click="step = 1">返回修改</a-button>
          <a-button type="primary" danger :loading="busy" :disabled="preview?.requiresRiskAcknowledgement && !riskAcknowledged" @click="archive">
            确认归档
          </a-button>
        </div>
      </section>

      <section v-else class="done-stage">
        <CheckCircle2 :size="48" />
        <h3>{{ completionMode === 'attachment_only' ? '附件已加入最近会话' : '归档完成' }}</h3>
        <p v-if="completionMode === 'attachment_only'">文件上传已成功；AI 摘要与档案归档尚未发生。本次无需重复上传。</p>
        <p v-else>相关业务视图与待办已同步更新。演示模式的变化保存在本机浏览器中。</p>
        <a-button type="primary" @click="emit('close')">{{ completionMode === 'attachment_only' ? '关闭' : '查看档案' }}</a-button>
      </section>
    </div>
  </a-modal>
</template>

<style scoped>
.flow-shell { padding-top: 6px; }
.flow-alert { margin-top: 20px; }
.upload-stage { display: grid; gap: 14px; padding: 32px 0 12px; }
.drop-zone { display: grid; justify-items: center; gap: 9px; min-height: 260px; padding: 30px; border: 1px dashed var(--main-300); border-radius: 16px; color: var(--main-700); background: linear-gradient(145deg, var(--main-30), var(--gray-0)); cursor: pointer; }
.drop-zone:hover { border-color: var(--main-600); }
.drop-zone span { color: var(--gray-600); }
.drop-zone .demo-copy { max-width: 470px; color: var(--gray-500); font-size: 12px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.draft-stage, .preview-stage { display: grid; gap: 18px; padding-top: 24px; }
.source-file { display: flex; gap: 10px; padding: 13px; border: 1px solid var(--gray-150); border-radius: 12px; background: var(--gray-25); }
.source-file div { display: grid; gap: 3px; min-width: 0; }
.source-file span { color: var(--gray-600); font-size: 12px; line-height: 1.5; }
.draft-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.draft-grid label { display: grid; gap: 7px; color: var(--gray-800); font-weight: 600; }
.flow-actions { display: flex; justify-content: flex-end; gap: 10px; padding-top: 4px; }
.stage-kicker { color: var(--main-700); font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.preview-stage h3, .done-stage h3 { margin: 6px 0; color: var(--gray-1000); }
.preview-stage > div > p, .done-stage p { margin: 0; color: var(--gray-600); }
.impact-list { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.impact-list li { display: grid; grid-template-columns: 100px 1fr; gap: 12px; padding: 13px; border: 1px solid var(--gray-150); border-radius: 10px; }
.impact-list li > span { color: var(--main-700); font-weight: 700; }
.impact-list p { margin: 3px 0 0; color: var(--gray-600); }
.risk-confirm { display: flex; gap: 10px; padding: 14px; border: 1px solid var(--color-error-100); border-radius: 10px; color: var(--color-error-700); background: var(--color-error-10); }
.done-stage { display: grid; justify-items: center; gap: 10px; padding: 64px 20px 40px; text-align: center; }
.done-stage svg { color: var(--color-success-500); }
@media (max-width: 600px) {
  .draft-grid { grid-template-columns: 1fr; }
  .impact-list li { grid-template-columns: 80px 1fr; }
  .flow-shell :deep(.ant-steps-item-title) { font-size: 11px; }
}
</style>
