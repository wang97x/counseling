<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({ series: { type: Array, default: () => [] } })
const chartElement = ref(null)
let chart

function renderChart() {
  if (!chartElement.value || !props.series.length) return
  chart ||= echarts.init(chartElement.value)
  const dates = [...new Set(props.series.flatMap((item) => item.points.map((point) => point.date)))]
  chart.setOption({
    animationDuration: 350,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: getComputedStyle(document.documentElement).getPropertyValue('--gray-700') } },
    grid: { left: 36, right: 18, top: 42, bottom: 28 },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: 'value', min: 0, max: 10, interval: 2 },
    series: props.series.map((item) => ({
      name: item.name,
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: dates.map((date) => item.points.find((point) => point.date === date)?.value ?? null),
      areaStyle: { opacity: 0.08 },
    })),
  }, true)
}

function resize() { chart?.resize() }
onMounted(() => {
  void nextTick(renderChart)
  window.addEventListener('resize', resize)
})
watch(() => props.series, () => void nextTick(renderChart), { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template>
  <div v-if="series.length" ref="chartElement" class="assessment-chart" role="img" aria-label="量表趋势图"></div>
  <a-empty v-else description="暂无量表记录" />
</template>

<style scoped>
.assessment-chart { width: 100%; height: 280px; }
</style>
