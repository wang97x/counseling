<script setup>
import { computed } from 'vue'

const props = defineProps({ level: { type: String, default: 'normal' } })
const meta = computed(() => ({
  normal: { label: '常规关注', color: 'success' },
  watch: { label: '持续观察', color: 'warning' },
  urgent: { label: '紧急关注', color: 'error' },
  high: { label: '高风险', color: 'error' },
}[props.level] || { label: '待评估', color: 'default' }))
</script>

<template>
  <a-tag :color="meta.color" class="risk-tag">{{ meta.label }}</a-tag>
</template>

<style scoped>
.risk-tag { margin: 0; border-radius: 999px; }
</style>
