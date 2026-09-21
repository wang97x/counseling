<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, CalendarDays, Plus, RefreshCw, RotateCcw, Search, UserRound } from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import RiskTag from '@/components/counseling/RiskTag.vue'
import { counselingWorkspaceService } from '@/services/counselingWorkspaceService.js'
import { useUserStore } from '@/stores/user'
import { message } from 'ant-design-vue'
import { createLatestOperation } from '@/utils/counselingRequestGuard.js'

const router = useRouter()
const service = counselingWorkspaceService
const userStore = useUserStore()
const students = ref([])
const createOpen = ref(false)
const createBusy = ref(false)
const createForm = reactive({ student_code: '' })
const loading = ref(false)
const error = ref('')
const filters = reactive({ query: '', riskLevel: undefined, status: undefined, appointment: undefined })
const listOperations = createLatestOperation()

async function loadStudents() {
  const operation = listOperations.begin()
  loading.value = true
  error.value = ''
  try {
    const result = await service.listStudents({ ...filters })
    if (!listOperations.isCurrent(operation)) return
    if (result.status !== 'ok') throw new Error(result.message || '加载档案失败')
    students.value = result.data
  } catch (cause) {
    if (!listOperations.isCurrent(operation)) return
    error.value = cause.message || '加载档案失败'
  } finally {
    if (listOperations.isCurrent(operation)) loading.value = false
  }
}

function openCreate() {
  createOpen.value = true
  createForm.student_code = ''
}

async function createStudent() {
  const code = createForm.student_code.trim()
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(code)) {
    message.error('学生编号须为 1–64 位字母、数字、下划线或连字符')
    return
  }
  createBusy.value = true
  try {
    const result = await service.createStudent({ student_code: code })
    if (result.status !== 'ok') throw new Error(result.message || '创建档案失败')
    createOpen.value = false
    message.success('学生档案已创建')
    await loadStudents()
  } catch (cause) {
    message.error(cause.message || '创建档案失败')
  } finally {
    createBusy.value = false
  }
}

async function resetDemo() {
  await service.resetDemo()
  Object.assign(filters, { query: '', riskLevel: undefined, status: undefined, appointment: undefined })
  await loadStudents()
}

function canOpen(item) {
  if (service.mode === 'demo') return true
  return userStore.businessRoles.includes('counselor') &&
    Number(item.counselorId) === Number(userStore.userId)
}

function displayCounselor(item) {
  return Number(item.counselorId) === Number(userStore.userId)
    ? userStore.username || '当前辅导员'
    : item.counselor
}

function openStudent(item) {
  if (!canOpen(item)) return
  void router.push({ name: 'StudentRecordDetail', params: { studentId: item.id } })
}

function clearFilters() {
  Object.assign(filters, { query: '', riskLevel: undefined, status: undefined, appointment: undefined })
  void loadStudents()
}

onMounted(loadStudents)
</script>

<template>
  <div class="records-page">
    <PageHeader title="心理辅导档案" :loading="loading" :show-border="true">
      <template #info><a-tag v-if="service.mode === 'demo'" color="gold">演示数据</a-tag></template>
      <template #actions>
        <a-button v-if="service.mode === 'demo'" aria-label="重置演示数据" title="重置演示数据" @click="resetDemo">
          <template #icon><RotateCcw :size="15" /></template>重置演示
        </a-button>
        <a-button aria-label="刷新档案列表" title="刷新档案列表" :disabled="loading" @click="loadStudents">
          <template #icon><RefreshCw :size="15" /></template>刷新
        </a-button>
        <a-button v-if="service.mode === 'api' && userStore.canCreateStudentRecord" type="primary" aria-label="新建档案" title="新建档案" @click="openCreate">
          <template #icon><Plus :size="15" /></template>新建档案
        </a-button>
      </template>
    </PageHeader>

    <main class="records-content">
      <section class="records-intro">
        <div>
          <span class="eyebrow">COUNSELING WORKSPACE</span>
          <h2>把每一次谈话，放回学生成长的上下文里</h2>
          <p>快速查看风险、预约和最近变化；进入档案后完成记录审阅与归档。</p>
        </div>
        <div class="intro-metric">
          <strong>{{ students.length }}</strong>
          <span>当前结果</span>
        </div>
      </section>

      <a-alert
        v-if="service.mode === 'demo'"
        type="warning"
        show-icon
        message="当前为演示数据模式"
        description="所有姓名与记录均为虚构内容，变化仅保存在本机浏览器，不构成生产档案或后端完成证据。"
      />

      <section class="filter-bar" aria-label="档案筛选">
        <a-input v-model:value="filters.query" allow-clear :placeholder="service.mode === 'api' ? '搜索编号或负责人' : '搜索编号、姓名、主诉或负责人'" @pressEnter="loadStudents">
          <template #prefix><Search :size="16" /></template>
        </a-input>
        <a-select v-model:value="filters.riskLevel" allow-clear :disabled="service.mode === 'api'" :placeholder="service.mode === 'api' ? '风险未接入' : '风险'" @change="loadStudents">
          <a-select-option value="normal">常规关注</a-select-option>
          <a-select-option value="watch">持续观察</a-select-option>
          <a-select-option value="high">高风险</a-select-option>
        </a-select>
        <a-select v-model:value="filters.status" allow-clear placeholder="状态" @change="loadStudents">
          <a-select-option value="active">辅导中</a-select-option>
          <a-select-option v-if="service.mode === 'demo'" value="paused">已暂停</a-select-option>
          <a-select-option value="closed">阶段结束</a-select-option>
        </a-select>
        <a-select v-model:value="filters.appointment" allow-clear :disabled="service.mode === 'api'" :placeholder="service.mode === 'api' ? '预约未接入' : '预约'" @change="loadStudents">
          <a-select-option value="upcoming">有后续预约</a-select-option>
        </a-select>
        <a-button type="primary" @click="loadStudents">筛选</a-button>
      </section>

      <a-alert v-if="error" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="loadStudents">重试</a-button></template>
      </a-alert>

      <div v-if="loading" class="student-grid">
        <a-card v-for="index in 3" :key="index"><a-skeleton active /></a-card>
      </div>
      <a-empty v-else-if="!students.length && !error" description="没有符合条件的档案">
        <a-button @click="clearFilters">清除筛选</a-button>
      </a-empty>
      <section v-else class="student-grid" aria-live="polite">
        <article
          v-for="item in students"
          :key="item.id"
          class="student-card"
          :class="{ locked: !canOpen(item) }"
          :tabindex="canOpen(item) ? 0 : -1"
          :aria-disabled="!canOpen(item)"
          @click="openStudent(item)"
          @keydown.enter="openStudent(item)"
        >
          <header>
            <div class="avatar"><UserRound :size="21" /></div>
            <div class="identity">
              <div><h3>{{ item.name }}</h3><span>{{ item.code }}</span></div>
              <p>{{ item.chiefConcern }}</p>
            </div>
            <RiskTag :level="item.riskLevel" />
          </header>
          <div class="card-facts">
            <div><span>当前次数</span><strong>{{ item.sessionCount == null ? '详情可见' : '第 ' + item.sessionCount + ' 次' }}</strong></div>
            <div><span>状态</span><strong>{{ item.status === 'closed' ? '阶段结束' : item.status === 'paused' ? '已暂停' : '辅导中' }}</strong></div>
            <div><span>负责人</span><strong>{{ displayCounselor(item) }}</strong></div>
          </div>
          <div class="appointment">
            <CalendarDays :size="16" />
            <span>{{ service.mode === 'api' ? '预约能力尚未接入' : item.nextAppointment ? '下次预约 ' + item.nextAppointment : '暂无后续预约' }}</span>
          </div>
          <footer>
            <span>{{ item.recentActivity }}</span>
            <span v-if="canOpen(item)" class="open-link">打开档案 <ArrowRight :size="15" /></span>
            <span v-else class="locked-copy">仅负责人可打开</span>
          </footer>
        </article>
      </section>
    </main>

    <a-modal v-model:open="createOpen" title="新建学生档案" :confirm-loading="createBusy" @ok="createStudent">
      <a-form layout="vertical">
        <a-form-item label="学生编号" required>
          <a-input v-model:value="createForm.student_code" placeholder="字母、数字、下划线或连字符" />
        </a-form-item>
        <a-alert type="info" show-icon message="档案创建后由你负责，仅你可以打开并维护档案正文。" />
      </a-form>
    </a-modal>
  </div>
</template>

<style scoped>
.records-page { min-height: 100%; color: var(--gray-900); background: var(--gray-25); }
.records-content { display: grid; gap: 20px; max-width: 1280px; margin: 0 auto; padding: 28px var(--page-padding) 48px; }
.records-intro { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 28px; overflow: hidden; border: 1px solid var(--gray-150); border-radius: 18px; background: radial-gradient(circle at 90% 10%, var(--second-50), transparent 32%), linear-gradient(135deg, var(--gray-0), var(--main-30)); }
.eyebrow { color: var(--main-700); font-size: 11px; font-weight: 800; letter-spacing: .13em; }
.records-intro h2 { margin: 8px 0; color: var(--gray-1000); font-size: clamp(22px, 3vw, 32px); line-height: 1.2; }
.records-intro p { margin: 0; color: var(--gray-600); }
.intro-metric { display: grid; min-width: 110px; padding: 14px; border: 1px solid var(--gray-150); border-radius: 14px; background: var(--gray-0); text-align: center; }
.intro-metric strong { color: var(--main-700); font-size: 30px; }
.intro-metric span { color: var(--gray-500); font-size: 12px; }
.filter-bar { display: grid; grid-template-columns: minmax(220px, 1fr) 140px 140px 150px auto; gap: 10px; padding: 14px; border: 1px solid var(--gray-150); border-radius: 14px; background: var(--gray-0); }
.student-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.student-card { display: grid; gap: 18px; padding: 20px; border: 1px solid var(--gray-150); border-radius: 16px; background: var(--gray-0); cursor: pointer; transition: border-color .18s ease, background-color .18s ease; }
.student-card:hover, .student-card:focus-visible { border-color: var(--main-300); outline: none; background: var(--main-30); }
.student-card.locked { cursor: default; }
.student-card.locked:hover { border-color: var(--gray-150); background: var(--gray-0); }
.student-card header { display: flex; align-items: flex-start; gap: 11px; }
.avatar { display: grid; place-items: center; flex: 0 0 40px; height: 40px; border-radius: 12px; color: var(--main-700); background: var(--main-50); }
.identity { flex: 1; min-width: 0; }
.identity > div { display: flex; align-items: baseline; gap: 8px; }
.identity h3 { margin: 0; color: var(--gray-1000); font-size: 17px; }
.identity span { color: var(--gray-500); font-size: 12px; }
.identity p { margin: 5px 0 0; color: var(--gray-600); font-size: 13px; line-height: 1.45; }
.card-facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.card-facts div { display: grid; gap: 3px; }
.card-facts span { color: var(--gray-500); font-size: 11px; }
.card-facts strong { color: var(--gray-800); font-size: 13px; }
.appointment { display: flex; align-items: center; gap: 7px; padding: 10px 11px; border-radius: 9px; color: var(--gray-700); background: var(--gray-50); font-size: 12px; }
.student-card footer { display: flex; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid var(--gray-100); color: var(--gray-500); font-size: 12px; }
.open-link { display: inline-flex; align-items: center; gap: 4px; color: var(--main-700); font-weight: 700; white-space: nowrap; }
.locked-copy { color: var(--gray-500); white-space: nowrap; }
@media (max-width: 1024px) {
  .student-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-bar { grid-template-columns: 1fr 1fr 1fr; }
  .filter-bar :first-child { grid-column: span 2; }
}
@media (max-width: 768px) {
  .records-content { padding-top: 18px; }
  .records-intro { align-items: flex-start; padding: 20px; }
  .intro-metric { display: none; }
  .student-grid { grid-template-columns: 1fr; }
}
@media (max-width: 500px) {
  :deep(.page-header-right .ant-tag) { display: none; }
  :deep(.page-header-right) { gap: 4px; }
  :deep(.page-header-right .ant-btn) { width: 30px; padding-inline: 6px; font-size: 0; }
  :deep(.page-header-right .ant-btn-icon) { margin-inline-end: 0; }
  .records-content { padding-inline: 14px; }
  .filter-bar { grid-template-columns: 1fr 1fr; }
  .filter-bar :first-child { grid-column: 1 / -1; }
  .student-card { padding: 16px; }
  .student-card footer { flex-direction: column; }
}
</style>
