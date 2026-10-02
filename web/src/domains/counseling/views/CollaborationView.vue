<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { useUserStore } from '@/stores/user'
import { counselingApi } from '../api'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const error = ref('')
const supervision = ref([])
const external = ref([])
const recipients = ref([])
const deliveries = ref([])
const dashboard = ref(null)
const materials = ref([])
const feedback = ref([])
const selectedAuthorization = ref(null)
const lastClaimToken = ref('')
const feedbackForm = reactive({ material_id: '', focus_area: 'process', comment: '' })
const supervisionForm = reactive({ supervisor_id: null, purpose: '', expires_days: 30 })
const externalForm = reactive({ recipient_id: '', expires_days: 30 })
const studentId = computed(() => Number(route.query.student_id) || null)
const isSupervisor = computed(() => userStore.businessRoles.includes('supervisor'))
const isManager = computed(() => userStore.businessRoles.includes('business_admin'))
const isCounselor = computed(() => userStore.businessRoles.includes('counselor'))

function requestId(prefix) {
  return `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`
}

function windowPayload(days, scopes) {
  const effective = new Date()
  const expires = new Date(effective.getTime() + Number(days) * 86400000)
  return {
    request_id: requestId('p3'),
    scopes,
    effective_from: effective.toISOString(),
    expires_at: expires.toISOString(),
  }
}

async function load() {
  loading.value = true
  error.value = ''
  selectedAuthorization.value = null
  materials.value = []
  feedback.value = []
  try {
    if (isSupervisor.value) {
      supervision.value = await counselingApi.listSupervisionAuthorizations()
    }
    if (isManager.value) {
      const [quality, supervisionRows, externalRows, recipientRows] = await Promise.all([
        counselingApi.getQualityDashboard('quarter'),
        counselingApi.listSupervisionAuthorizations(),
        counselingApi.listExternalAuthorizations(),
        counselingApi.listExternalRecipients(),
      ])
      dashboard.value = quality
      supervision.value = supervisionRows
      external.value = externalRows
      recipients.value = recipientRows
    }
    if (isCounselor.value && studentId.value) {
      const [supervisionRows, externalRows, deliveryRows, recipientRows] = await Promise.all([
        counselingApi.listSupervisionAuthorizations(studentId.value),
        counselingApi.listExternalAuthorizations(studentId.value),
        counselingApi.listExternalDeliveries(studentId.value),
        counselingApi.listExternalRecipients(),
      ])
      supervision.value = supervisionRows
      external.value = externalRows
      deliveries.value = deliveryRows
      recipients.value = recipientRows
    }
  } catch (cause) {
    error.value = cause.message || '授权协作数据加载失败'
  } finally {
    loading.value = false
  }
}

async function openSupervision(item) {
  selectedAuthorization.value = item
  try {
    const [materialRows, feedbackRows] = await Promise.all([
      counselingApi.listSupervisionMaterials(item.id),
      counselingApi.listSupervisionFeedback(item.id),
    ])
    materials.value = materialRows
    feedback.value = feedbackRows
    feedbackForm.material_id = materialRows[0]?.id || ''
  } catch (cause) {
    message.error(cause.message || '督导材料加载失败')
  }
}

async function decide(kind, item, decision) {
  const note = window.prompt(decision === 'approved' ? '请输入批准说明' : '请输入拒绝说明')
  if (!note?.trim()) return
  const payload = { expected_version: item.version, decision, note: note.trim() }
  try {
    if (kind === 'supervision') {
      await counselingApi.decideSupervisionAuthorization(item.id, payload)
    } else {
      await counselingApi.decideExternalAuthorization(item.id, payload)
    }
    message.success('授权决定已保存')
    await load()
  } catch (cause) {
    message.error(cause.message || '授权处理失败')
  }
}

async function submitFeedback() {
  if (!selectedAuthorization.value || !feedbackForm.material_id || !feedbackForm.comment.trim()) return
  try {
    await counselingApi.createSupervisionFeedback(selectedAuthorization.value.id, {
      request_id: requestId('feedback'),
      material_id: feedbackForm.material_id,
      focus_area: feedbackForm.focus_area,
      comment: feedbackForm.comment.trim(),
    })
    feedbackForm.comment = ''
    await openSupervision(selectedAuthorization.value)
    message.success('督导意见已追加')
  } catch (cause) {
    message.error(cause.message || '督导意见保存失败')
  }
}

async function requestSupervision() {
  if (!studentId.value || !supervisionForm.supervisor_id || !supervisionForm.purpose.trim()) return
  try {
    await counselingApi.createSupervisionAuthorization(studentId.value, {
      ...windowPayload(supervisionForm.expires_days, [
        'case_overview', 'supervision_feedback', 'supervision_summary',
      ]),
      supervisor_id: Number(supervisionForm.supervisor_id),
      purpose: supervisionForm.purpose.trim(),
    })
    supervisionForm.purpose = ''
    message.success('督导授权已提交业务管理员审批')
    await load()
  } catch (cause) {
    message.error(cause.message || '督导授权提交失败')
  }
}

async function requestExternal() {
  if (!studentId.value || !externalForm.recipient_id) return
  try {
    await counselingApi.createExternalAuthorization(studentId.value, {
      ...windowPayload(externalForm.expires_days, ['resource_catalog', 'referral_status']),
      recipient_id: externalForm.recipient_id,
    })
    message.success('外发授权已提交业务管理员审批')
    await load()
  } catch (cause) {
    message.error(cause.message || '外发授权提交失败')
  }
}

async function publishMaterial(item) {
  try {
    await counselingApi.publishSupervisionMaterial(studentId.value, item.id, {
      request_id: requestId('material'),
      stage: 'review',
      concern_tags: ['other'],
    })
    message.success('结构化去标识材料已发布')
    await openSupervision(item)
  } catch (cause) {
    message.error(cause.message || '材料发布失败')
  }
}

async function prepareDelivery(item) {
  const code = window.prompt('请输入获准资源编号（字母、数字、下划线或连字符）')
  if (!code?.trim()) return
  try {
    const expires = new Date(Date.now() + 86400000)
    const result = await counselingApi.createExternalDelivery(studentId.value, item.id, {
      request_id: requestId('delivery'),
      scopes: ['resource_catalog'],
      resource_codes: [code.trim()],
      token_expires_at: expires.toISOString(),
    })
    lastClaimToken.value = result.claim_token || ''
    message.success('交付已准备；只有接收方领取后才记为已送达')
    await load()
  } catch (cause) {
    message.error(cause.message || '交付准备失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="collaboration-page">
    <PageHeader title="授权协作" :loading="loading" :show-border="true">
      <template #actions>
        <a-button :disabled="loading" @click="load">刷新</a-button>
      </template>
    </PageHeader>

    <main class="collaboration-content">
      <a-alert
        v-if="error"
        type="error"
        show-icon
        :message="error"
      />
      <a-alert
        v-if="isCounselor && !studentId"
        type="info"
        show-icon
        message="请从具体学生档案进入授权协作"
      >
        <template #action><a-button @click="router.push('/students')">返回学生档案</a-button></template>
      </a-alert>
      <a-alert
        v-if="lastClaimToken"
        type="warning"
        show-icon
        message="一次性领取令牌仅在本次创建响应显示"
        :description="lastClaimToken"
        closable
        @close="lastClaimToken = ''"
      />

      <template v-if="isManager && dashboard">
        <section class="section">
          <h2>质量看板 · 近 90 天</h2>
          <p class="section-note">指标口径由服务端固定；少于 {{ dashboard.minimum_cohort }} 个个案时隐藏数值。</p>
          <div class="metric-grid">
            <article v-for="metric in dashboard.metrics" :key="metric.code">
              <span>{{ metric.definition }}</span>
              <strong>{{ metric.suppressed ? '样本不足' : metric.numerator }}</strong>
              <small v-if="!metric.suppressed">{{ metric.numerator }} / {{ metric.denominator }}</small>
            </article>
          </div>
        </section>
      </template>

      <section v-if="isCounselor && studentId" class="section form-grid">
        <a-card title="申请督导授权">
          <a-form layout="vertical" @finish="requestSupervision">
            <a-form-item label="督导账号 ID" required>
              <a-input-number v-model:value="supervisionForm.supervisor_id" :min="1" />
            </a-form-item>
            <a-form-item label="授权目的" required>
              <a-textarea v-model:value="supervisionForm.purpose" :rows="2" />
            </a-form-item>
            <a-button type="primary" html-type="submit">提交审批</a-button>
          </a-form>
        </a-card>
        <a-card title="申请外发授权">
          <a-form layout="vertical" @finish="requestExternal">
            <a-form-item label="已核验接收方" required>
              <a-select v-model:value="externalForm.recipient_id">
                <a-select-option v-for="item in recipients" :key="item.id" :value="item.id">
                  {{ item.display_name }} · {{ item.purpose }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-button type="primary" html-type="submit">提交审批</a-button>
          </a-form>
        </a-card>
      </section>

      <section class="section">
        <h2>督导授权</h2>
        <a-empty v-if="!supervision.length" description="暂无可见督导授权" />
        <div v-else class="card-list">
          <a-card v-for="item in supervision" :key="item.id" size="small">
            <div class="card-title">
              <strong>{{ item.purpose || '已授权督导个案' }}</strong>
              <a-tag :color="item.status === 'active' ? 'green' : 'default'">{{ item.status }}</a-tag>
            </div>
            <p>范围：{{ item.scopes.join('、') }}</p>
            <p>有效期至：{{ item.expires_at }}</p>
            <a-space>
              <a-button v-if="item.status === 'active'" size="small" @click="openSupervision(item)">查看材料</a-button>
              <a-button
                v-if="isCounselor && item.status === 'active'"
                size="small"
                @click="publishMaterial(item)"
              >发布去标识材料</a-button>
              <template v-if="isManager && item.status === 'pending'">
                <a-button size="small" type="primary" @click="decide('supervision', item, 'approved')">批准</a-button>
                <a-button size="small" danger @click="decide('supervision', item, 'rejected')">拒绝</a-button>
              </template>
            </a-space>
          </a-card>
        </div>
      </section>

      <section v-if="selectedAuthorization" class="section two-column">
        <a-card title="结构化去标识材料">
          <a-empty v-if="!materials.length" description="尚未发布材料" />
          <article v-for="item in materials" :key="item.id" class="material">
            <strong>{{ item.case_alias }} · {{ item.stage }}</strong>
            <p>主题：{{ item.concern_tags.join('、') || '未标注' }}</p>
            <p>会谈 {{ item.session_count }} · 量表 {{ item.assessment_count }} · 风险事件 {{ item.risk_event_count }}</p>
          </article>
        </a-card>
        <a-card title="督导意见">
          <article v-for="item in feedback" :key="item.id" class="material">
            <a-tag>{{ item.focus_area }}</a-tag>
            <p>{{ item.comment }}</p>
          </article>
          <a-form v-if="isSupervisor" layout="vertical" @finish="submitFeedback">
            <a-form-item label="材料" required>
              <a-select v-model:value="feedbackForm.material_id">
                <a-select-option v-for="item in materials" :key="item.id" :value="item.id">
                  {{ item.case_alias }} · v{{ item.version_no }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="关注面" required>
              <a-select v-model:value="feedbackForm.focus_area">
                <a-select-option value="case_conceptualization">个案概念化</a-select-option>
                <a-select-option value="process">过程</a-select-option>
                <a-select-option value="ethics">伦理</a-select-option>
                <a-select-option value="risk">风险</a-select-option>
                <a-select-option value="referral">转介</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="意见" required>
              <a-textarea v-model:value="feedbackForm.comment" :rows="3" />
            </a-form-item>
            <a-button type="primary" html-type="submit">追加意见</a-button>
          </a-form>
        </a-card>
      </section>

      <section v-if="isManager || (isCounselor && studentId)" class="section">
        <h2>外发授权与交付</h2>
        <a-empty v-if="!external.length" description="暂无外发授权" />
        <div v-else class="card-list">
          <a-card v-for="item in external" :key="item.id" size="small">
            <div class="card-title">
              <strong>接收方 {{ item.recipient_id }}</strong>
              <a-tag :color="item.status === 'active' ? 'green' : 'default'">{{ item.status }}</a-tag>
            </div>
            <p>最小范围：{{ item.scopes.join('、') }}</p>
            <a-space>
              <a-button
                v-if="isCounselor && item.status === 'active'"
                size="small"
                type="primary"
                @click="prepareDelivery(item)"
              >准备一次性交付</a-button>
              <template v-if="isManager && item.status === 'pending'">
                <a-button size="small" type="primary" @click="decide('external', item, 'approved')">批准</a-button>
                <a-button size="small" danger @click="decide('external', item, 'rejected')">拒绝</a-button>
              </template>
            </a-space>
          </a-card>
        </div>
        <a-table
          v-if="isCounselor && deliveries.length"
          class="delivery-table"
          :data-source="deliveries"
          :pagination="false"
          row-key="id"
          :columns="[
            { title: '范围', dataIndex: 'scopes' },
            { title: '状态', dataIndex: 'status' },
            { title: '失败次数', dataIndex: 'failed_attempts' },
            { title: '送达时间', dataIndex: 'delivered_at' },
          ]"
        />
      </section>
    </main>
  </div>
</template>

<style scoped>
.collaboration-page { min-height: 100%; background: var(--color-bg-layout); }
.collaboration-content { display: grid; gap: 20px; padding: 24px; }
.section { padding: 20px; border: 1px solid var(--color-border-secondary); border-radius: 14px; background: var(--color-bg-container); }
.section h2 { margin: 0 0 12px; font-size: 18px; }
.section-note { color: var(--color-text-secondary); }
.metric-grid, .form-grid, .two-column { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.metric-grid article { display: grid; gap: 6px; padding: 14px; border-radius: 10px; background: var(--color-fill-quaternary); }
.metric-grid strong { font-size: 22px; }
.card-list { display: grid; gap: 12px; }
.card-title { display: flex; justify-content: space-between; gap: 12px; }
.material { padding: 10px 0; border-bottom: 1px solid var(--color-border-secondary); }
.delivery-table { margin-top: 16px; }
@media (max-width: 800px) {
  .metric-grid, .form-grid, .two-column { grid-template-columns: 1fr; }
  .collaboration-content { padding: 16px; }
}
</style>
