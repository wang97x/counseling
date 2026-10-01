<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ShieldCheck } from '@lucide/vue'
import { counselingApi } from '../api.js'

const route = useRoute()
const router = useRouter()
const notice = ref(null)
const checked = ref(false)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')

function safeRedirect() {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  if (!target.startsWith('/students') || target.startsWith('/students/data-use-notice')) {
    return '/students'
  }
  return target
}

async function loadNotice() {
  loading.value = true
  error.value = ''
  try {
    notice.value = await counselingApi.getDataUseNotice()
    checked.value = notice.value.acknowledged
  } catch (cause) {
    error.value = cause.message || '无法读取数据用途告知'
  } finally {
    loading.value = false
  }
}

async function continueToWorkspace() {
  if (!notice.value || (!notice.value.acknowledged && !checked.value)) return
  submitting.value = true
  error.value = ''
  try {
    if (!notice.value.acknowledged) {
      notice.value = await counselingApi.acknowledgeDataUseNotice(notice.value.version)
    }
    await router.replace(safeRedirect())
  } catch (cause) {
    error.value = cause.message || '确认失败，请重试'
  } finally {
    submitting.value = false
  }
}

onMounted(loadNotice)
</script>

<template>
  <main class="notice-page">
    <a-card class="notice-card" :bordered="false">
      <a-skeleton v-if="loading" active />
      <template v-else>
        <div class="notice-icon"><ShieldCheck :size="30" /></div>
        <h1>{{ notice?.title || '心理辅导数据用途告知' }}</h1>
        <p class="lead">进入档案工作区前，请阅读系统如何处理心理辅导业务数据。</p>

        <a-alert
          v-if="error"
          type="error"
          show-icon
          :message="error"
          description="未读取或确认成功前，系统不会加载学生档案。"
        >
          <template #action>
            <a-button size="small" @click="loadNotice">重试</a-button>
          </template>
        </a-alert>

        <ul v-if="notice" class="notice-items">
          <li v-for="item in notice.items" :key="item">{{ item }}</li>
        </ul>

        <a-alert
          v-if="notice"
          type="info"
          show-icon
          message="这是数据用途告知，不代表来访者授权或临床知情同意。"
        />

        <a-checkbox
          v-if="notice && !notice.acknowledged"
          v-model:checked="checked"
          class="acknowledgment"
        >
          我已阅读当前版本（{{ notice.version }}）并了解上述系统边界
        </a-checkbox>
        <p v-else-if="notice?.acknowledged" class="acknowledged">
          已于 {{ notice.acknowledged_at }} 确认当前版本
        </p>

        <a-button
          type="primary"
          size="large"
          block
          :disabled="!notice || (!notice.acknowledged && !checked)"
          :loading="submitting"
          @click="continueToWorkspace"
        >
          {{ notice?.acknowledged ? '进入档案工作区' : '确认并进入' }}
        </a-button>
      </template>
    </a-card>
  </main>
</template>

<style scoped>
.notice-page {
  display: grid;
  min-height: 100%;
  place-items: center;
  padding: 32px var(--page-padding);
  background: var(--gray-25);
}
.notice-card {
  width: min(680px, 100%);
  border: 1px solid var(--gray-150);
  border-radius: 18px;
  box-shadow: 0 18px 48px rgb(15 23 42 / 8%);
}
.notice-icon {
  display: grid;
  width: 56px;
  height: 56px;
  margin-bottom: 18px;
  place-items: center;
  border-radius: 16px;
  color: var(--main-700);
  background: var(--main-50);
}
h1 { margin: 0 0 8px; color: var(--gray-1000); font-size: 28px; }
.lead { margin: 0 0 22px; color: var(--gray-600); line-height: 1.7; }
.notice-items { display: grid; gap: 12px; margin: 22px 0; padding-left: 22px; color: var(--gray-800); line-height: 1.65; }
.acknowledgment { margin: 22px 0; color: var(--gray-800); }
.acknowledged { margin: 22px 0; color: var(--main-700); font-weight: 600; }
</style>
