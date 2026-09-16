<script setup>
import { computed, ref } from 'vue'
import { ArrowRight, Bot, BookOpen, Send, Sparkles } from '@lucide/vue'

const props = defineProps({
  open: Boolean,
  student: { type: Object, default: null },
  messages: { type: Array, default: () => [] },
  busy: Boolean,
  mode: { type: String, default: 'api' },
  nextStepTopics: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'send'])
const input = ref('')
const scopeText = computed(() => props.student ? '当前档案 · 时间轴 · 目标 · 风险记录' : '未选择档案')

function submit(intent = 'next_step', preset = '') {
  const content = (preset || input.value).trim()
  if (!content || props.busy) return
  emit('send', { content, intent })
  input.value = ''
}
</script>

<template>
  <a-drawer
    :open="open"
    placement="right"
    :width="440"
    root-class-name="counseling-assistant-drawer"
    :closable="false"
    @close="emit('close')"
  >
    <template #title>
      <div class="drawer-title">
        <span class="assistant-icon"><Bot :size="18" /></span>
        <span>下一步助手</span>
        <a-tag color="blue">档案内</a-tag>
      </div>
    </template>
    <template #extra><a-button type="text" @click="emit('close')">关闭</a-button></template>

    <section class="assistant-context">
      <div>
        <span class="eyebrow">当前学生</span>
        <strong>{{ student?.name || '未选择' }}</strong>
      </div>
      <div>
        <span class="eyebrow">当前阶段</span>
        <strong>{{ student?.status === 'closed' ? '阶段结束' : '持续辅导' }}</strong>
      </div>
      <p>{{ scopeText }}</p>
      <a-alert v-if="mode === 'demo'" type="warning" show-icon message="演示模式请勿输入真实个人或敏感信息" class="privacy-alert" />
      <a-alert v-else type="info" show-icon message="后端辅导助手能力尚未接入" class="privacy-alert" />
    </section>

    <section class="next-step-section">
      <div class="section-heading">
        <div><span class="eyebrow">推荐话题</span><strong>下一步可以做什么</strong></div>
        <span>{{ nextStepTopics.length }} 项</span>
      </div>
      <div class="topic-list">
        <button v-for="topic in nextStepTopics" :key="topic.id" type="button" :disabled="busy" @click="submit('next_step', topic.prompt)">
          <span><strong>{{ topic.title }}</strong><small :title="topic.description">{{ topic.description }}</small></span>
          <ArrowRight :size="16" />
        </button>
      </div>
    </section>

    <div class="quick-actions">
      <button type="button" :disabled="busy" @click="submit('adjust', '帮我检查摘要中需要人工核对的内容')">
        <Sparkles :size="17" />摘要调整
      </button>
      <button type="button" :disabled="busy" @click="submit('knowledge', '基于当前资料给出可核对的知识提示')">
        <BookOpen :size="17" />知识问答
      </button>
    </div>

    <div class="assistant-messages" aria-live="polite">
      <div v-if="!messages.length" class="assistant-empty">
        助手会保留当前学生上下文，但不会把建议当作已完成的专业判断。
      </div>
      <article v-for="item in messages" :key="item.id" :class="['assistant-message', item.role]">
        <span>{{ item.role === 'assistant' ? '助手' : '你' }}</span>
        <p>{{ item.content }}</p>
      </article>
      <article v-if="busy" class="assistant-message assistant"><span>助手</span><p>正在整理当前档案…</p></article>
    </div>

    <div class="assistant-composer">
      <label for="custom-next-step">自定义下一步话题</label>
      <div>
        <a-textarea
          id="custom-next-step"
          v-model:value="input"
          :auto-size="{ minRows: 2, maxRows: 5 }"
          placeholder="例如：讨论睡眠记录，并约定一项本周行动"
          @keydown.meta.enter.prevent="submit()"
          @keydown.ctrl.enter.prevent="submit()"
        />
        <a-button type="primary" :loading="busy" :disabled="!input.trim()" @click="submit()">
          <template #icon><Send :size="16" /></template>
          生成建议
        </a-button>
      </div>
    </div>
  </a-drawer>
</template>

<style scoped>
.drawer-title, .quick-actions, .assistant-composer > div { display: flex; align-items: center; gap: 8px; }
.assistant-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; color: var(--main-700); background: var(--main-50); }
.assistant-context { padding: 16px; border: 1px solid var(--gray-150); border-radius: 14px; background: linear-gradient(135deg, var(--main-30), var(--gray-0)); }
.assistant-context > div { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.assistant-context p { margin: 12px 0 0; padding-top: 10px; border-top: 1px solid var(--gray-150); color: var(--gray-600); font-size: 12px; }
.privacy-alert { margin-top: 12px; }
.eyebrow { color: var(--gray-500); font-size: 12px; }
.next-step-section { margin: 14px 0; padding: 14px; border: 1px solid var(--gray-150); border-radius: 14px; background: var(--gray-25); }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.section-heading > div { display: grid; gap: 3px; }
.section-heading > span { color: var(--gray-500); font-size: 11px; }
.topic-list { display: grid; gap: 8px; }
.topic-list button { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; padding: 11px 12px; border: 1px solid var(--gray-150); border-radius: 10px; color: var(--main-700); background: var(--gray-0); text-align: left; cursor: pointer; }
.topic-list button:hover { border-color: var(--main-300); background: var(--main-30); }
.topic-list button:disabled { cursor: not-allowed; opacity: .55; }
.topic-list button span { display: grid; gap: 3px; min-width: 0; }
.topic-list strong { color: var(--gray-800); font-size: 13px; }
.topic-list small { overflow: hidden; color: var(--gray-500); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.quick-actions { margin: 0 0 14px; }
.quick-actions button { flex: 1; display: grid; justify-items: center; gap: 6px; padding: 10px 4px; border: 1px solid var(--gray-150); border-radius: 10px; color: var(--gray-700); background: var(--gray-0); font-size: 12px; cursor: pointer; }
.quick-actions button:not(:disabled):hover { border-color: var(--main-300); color: var(--main-700); background: var(--main-30); }
.quick-actions button:disabled { cursor: not-allowed; opacity: .55; }
.assistant-messages { display: flex; flex-direction: column; gap: 12px; min-height: 190px; max-height: calc(100vh - 560px); padding: 4px 2px 16px; overflow: auto; }
.assistant-empty { padding: 30px 20px; color: var(--gray-500); text-align: center; }
.assistant-message { max-width: 88%; }
.assistant-message.user { align-self: flex-end; }
.assistant-message span { display: block; margin: 0 6px 4px; color: var(--gray-500); font-size: 11px; }
.assistant-message p { margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--gray-50); color: var(--gray-800); line-height: 1.65; }
.assistant-message.user p { color: var(--gray-0); background: var(--main-700); }
.assistant-composer { display: grid; gap: 7px; padding-top: 12px; border-top: 1px solid var(--gray-150); }
.assistant-composer label { color: var(--gray-700); font-size: 12px; font-weight: 700; }
.assistant-composer > div { align-items: flex-end; }
.assistant-composer :deep(.ant-input) { flex: 1; }
@media (max-width: 600px) {
  .quick-actions { align-items: stretch; }
  .assistant-messages { max-height: calc(100vh - 570px); }
}
</style>

<style>
@media (max-width: 600px) {
  .counseling-assistant-drawer .ant-drawer-content-wrapper { width: 100vw !important; }
}
</style>
