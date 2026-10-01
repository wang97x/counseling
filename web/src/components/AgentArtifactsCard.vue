<template>
  <section v-if="normalizedArtifacts.length" class="artifacts-list">
    <div v-for="file in normalizedArtifacts" :key="file.path" class="artifact-card">
      <button
        type="button"
        class="item-main"
        :title="`打开 ${file.name}`"
        @click="openPreview(file)"
      >
        <FileTypeIcon :name="file.path" :size="20" class="item-icon" />
        <div class="item-meta">
          <div class="item-name">{{ file.name }}</div>
          <div class="item-desc">{{ getFileMetaLabel(file.path) }}</div>
        </div>
      </button>
      <div class="item-actions">
        <button class="item-action-btn" title="下载" @click.stop="downloadFile(file)">
          <Download :size="15" />
        </button>
        <button
          v-if="workItemId"
          class="item-action-btn"
          :title="isSaving(file.path) ? '回填中' : '回填档案'"
          :disabled="isSaving(file.path) || !runId"
          @click.stop="openImportDialog(file)"
        >
          <LoaderCircle v-if="isSaving(file.path)" :size="15" class="item-action-spin" />
          <Inbox v-else :size="15" />
        </button>
        <button
          v-else
          class="item-action-btn"
          :title="isSaving(file.path) ? '保存中' : '保存到个人空间'"
          :disabled="isSaving(file.path)"
          @click.stop="saveToWorkspace(file)"
        >
          <LoaderCircle v-if="isSaving(file.path)" :size="15" class="item-action-spin" />
          <Save v-else :size="15" />
        </button>
      </div>
    </div>
  </section>

  <a-modal
    :open="saveDialogOpen"
    title="保存交付物"
    ok-text="保存"
    cancel-text="取消"
    :ok-button-props="{ disabled: !selectedDestination || pickerLoading }"
    :confirm-loading="pendingSaveFile ? isSaving(pendingSaveFile.path) : false"
    @ok="confirmSave"
    @cancel="closeSaveDialog"
  >
    <p class="save-dialog-hint">选择保存到个人工作区的目录</p>
    <WorkspacePathPicker
      v-model="selectedDestination"
      selection-mode="directory"
      :active="saveDialogOpen"
      :disabled="pendingSaveFile ? isSaving(pendingSaveFile.path) : false"
      @loading-change="pickerLoading = $event"
    />
  </a-modal>

  <a-modal
    :open="importDialogOpen"
    title="回填档案"
    ok-text="进入待整理区"
    cancel-text="取消"
    :confirm-loading="pendingImportFile ? isSaving(pendingImportFile.path) : false"
    @ok="confirmImport"
    @cancel="closeImportDialog"
  >
    <a-alert type="info" show-icon message="文件将进入当前学生的待整理区，仍需人工确认后才成为档案材料。" />
    <dl v-if="pendingImportFile" class="import-summary">
      <dt>目标学生</dt><dd>{{ studentId }}</dd>
      <dt>文件名</dt><dd>{{ importMetadata?.file_name || pendingImportFile.name }}</dd>
      <dt>类型</dt><dd>{{ importMetadata?.content_type || getFileMetaLabel(pendingImportFile.path) }}</dd>
      <dt>大小</dt><dd>{{ importMetadata ? formatBytes(importMetadata.size) : '正在校验…' }}</dd>
    </dl>
  </a-modal>
</template>

<script setup>
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { Download, Inbox, LoaderCircle, Save } from '@lucide/vue'
import { threadApi } from '@/apis/agent_api'
import { counselingApi } from '@/domains/counseling/api'
import FileTypeIcon from '@/components/common/FileTypeIcon.vue'
import WorkspacePathPicker from '@/components/WorkspacePathPicker.vue'
import { parseDownloadFilename } from '@/utils/file_utils'

const props = defineProps({
  artifacts: {
    type: Array,
    default: () => []
  },
  threadId: {
    type: String,
    default: null
  },
  runId: {
    type: String,
    default: null
  },
  studentId: {
    type: [String, Number],
    default: null
  },
  workItemId: {
    type: String,
    default: null
  }
})
const emit = defineEmits(['saved', 'open-preview'])

const normalizedArtifacts = computed(() =>
  (props.artifacts || [])
    .filter((path) => typeof path === 'string' && path.trim())
    .map((path) => {
      const normalizedPath = path.trim()
      return {
        path: normalizedPath,
        name: normalizedPath.split('/').pop() || normalizedPath
      }
    })
)
const savingState = ref({})
const saveDialogOpen = ref(false)
const pendingSaveFile = ref(null)
const selectedDestination = ref('/saved_artifacts')
const pickerLoading = ref(false)
const importDialogOpen = ref(false)
const pendingImportFile = ref(null)
const importMetadata = ref(null)
const importRequestId = ref(null)

const getFileMetaLabel = (path) => {
  const filename =
    String(path || '')
      .split('/')
      .pop() || ''
  if (!filename.includes('.')) return '交付文件'

  const extension = filename.split('.').pop()
  return extension ? `交付文件 · ${extension.toUpperCase()}` : '交付文件'
}

const formatBytes = (size) => {
  const value = Number(size)
  if (!Number.isFinite(value) || value < 0) return '未知'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

const openPreview = (file) => {
  emit('open-preview', { ...file })
}

const downloadFile = async (file) => {
  if (!props.threadId || !file?.path) return

  try {
    const response = await threadApi.downloadThreadArtifact(props.threadId, file.path)
    const blob = await response.blob()
    const contentDisposition =
      response.headers.get('Content-Disposition') || response.headers.get('content-disposition')
    const filename = parseDownloadFilename(contentDisposition) || file.name
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    message.error(error?.message || '下载文件失败')
  }
}

const isSaving = (path) => !!savingState.value[path]

const setSaving = (path, saving) => {
  savingState.value = {
    ...savingState.value,
    [path]: saving
  }
}

const saveToWorkspace = (file) => {
  if (!props.threadId || !file?.path || isSaving(file.path)) {
    return
  }
  pendingSaveFile.value = file
  selectedDestination.value = '/saved_artifacts'
  saveDialogOpen.value = true
}

const closeSaveDialog = () => {
  if (pendingSaveFile.value && isSaving(pendingSaveFile.value.path)) return
  saveDialogOpen.value = false
  pendingSaveFile.value = null
}

const confirmSave = async () => {
  const file = pendingSaveFile.value
  if (!props.threadId || !file?.path || !selectedDestination.value || isSaving(file.path)) return

  setSaving(file.path, true)
  try {
    const result = await threadApi.saveThreadArtifactToWorkspace(
      props.threadId,
      file.path,
      selectedDestination.value
    )
    message.success(`已保存到个人空间：${result.saved_path}`)
    emit('saved', result)
    saveDialogOpen.value = false
    pendingSaveFile.value = null
  } catch (error) {
    message.error(error?.message || '保存到个人空间失败')
  } finally {
    setSaving(file.path, false)
  }
}

const openImportDialog = async (file) => {
  if (!props.studentId || !props.workItemId || !props.runId || isSaving(file.path)) return
  setSaving(file.path, true)
  try {
    importMetadata.value = await counselingApi.preflightMaterial(props.studentId, props.workItemId, {
      run_id: props.runId,
      path: file.path
    })
  } catch (error) {
    message.error(error?.message || '文件校验失败')
    return
  } finally {
    setSaving(file.path, false)
  }
  pendingImportFile.value = file
  importRequestId.value = crypto.randomUUID()
  importDialogOpen.value = true
}

const closeImportDialog = () => {
  if (pendingImportFile.value && isSaving(pendingImportFile.value.path)) return
  importDialogOpen.value = false
  pendingImportFile.value = null
  importMetadata.value = null
  importRequestId.value = null
}

const confirmImport = async () => {
  const file = pendingImportFile.value
  if (!file || !importRequestId.value || !props.runId || !props.workItemId || !props.studentId || isSaving(file.path)) return
  setSaving(file.path, true)
  try {
    await counselingApi.importMaterial(props.studentId, props.workItemId, {
      request_id: importRequestId.value,
      run_id: props.runId,
      path: file.path
    })
    message.success('已进入待整理区')
    importDialogOpen.value = false
    pendingImportFile.value = null
    importMetadata.value = null
    importRequestId.value = null
    emit('saved', { kind: 'counseling_material', path: file.path })
  } catch (error) {
    message.error(error?.message || '回填档案失败')
  } finally {
    setSaving(file.path, false)
  }
}
</script>

<style scoped lang="less">
.import-summary {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 9px 12px;
  margin: 18px 0 0;
}

.import-summary dt { color: var(--gray-500); }
.import-summary dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.save-dialog-hint {
  margin-bottom: 12px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.artifacts-list {
  width: 100%;
  margin: 8px 0 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.artifact-card {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: linear-gradient(180deg, var(--gray-25) 0%, var(--gray-0) 100%);
  transition:
    background 0.18s ease,
    border-color 0.18s ease;

  &:hover {
    border-color: var(--main-200);
    background: var(--gray-0);
  }
}

.item-main {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  border: none;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  padding: 10px 8px 10px 12px;
}

.item-icon {
  flex-shrink: 0;
  font-size: 18px;
  opacity: 0.86;
}

.item-meta {
  min-width: 0;
  flex: 1;
}

.item-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-900);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.3;
}

.item-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--gray-500);
  line-height: 1.2;
}

.item-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-right: 8px;
}

.item-action-btn {
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  color: var(--gray-600);
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.item-action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.item-action-btn:hover:not(:disabled) {
  color: var(--main-700);
  background: var(--gray-100);
}

.item-action-spin {
  animation: artifacts-spin 1s linear infinite;
}

@keyframes artifacts-spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .artifacts-list {
    margin-top: 6px;
  }

  .artifact-card {
    align-items: stretch;
  }

  .item-main {
    padding: 9px 6px 9px 12px;
  }
}
</style>
