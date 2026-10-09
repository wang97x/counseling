import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'
import { formatLocalDateTime } from '../../src/domains/counseling/dateTime.js'

const source = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('心理辅导前端代码收敛到独立领域目录', () => {
  const oldPaths = [
    '../../src/apis/counseling_api.js',
    '../../src/services/counselingWorkspaceService.js',
    '../../src/types/counseling.js',
    '../../src/utils/counselingRequestGuard.js',
    '../../src/views/StudentWorkspaceView.vue',
  ]

  assert.ok(existsSync(new URL('../../src/domains/counseling/api.js', import.meta.url)))
  for (const path of oldPaths) assert.equal(existsSync(new URL(path, import.meta.url)), false, path)
})

test('档案 AI 协作通过业务 API 发起而不直连通用线程入口', () => {
  const api = source('../../src/domains/counseling/api.js')

  assert.match(api, /studentRoot\(studentId\).*\/ai-work-items/)
  assert.match(api, /materials\/import/)
  assert.doesNotMatch(api, /\/api\/chat\/thread/)
})

test('工作台和交付卡片暴露人工回填而不自动进入正式记录', () => {
  const workspace = source('../../src/domains/counseling/views/StudentWorkspaceView.vue')
  const artifacts = source('../../src/components/AgentArtifactsCard.vue')
  const chat = source('../../src/components/AgentChatComponent.vue')

  assert.match(workspace, />AI 协助</)
  assert.match(workspace, />待整理</)
  assert.match(workspace, />档案材料</)
  assert.match(artifacts, /回填档案/)
  assert.match(artifacts, /run_id: props\.runId/)
  assert.match(chat, /:run-id="row\.conv\.run\?\.run_id \|\| null"/)
  assert.match(chat, /资料仅供参考，不会自动改变档案、风险或业务状态/)
})

test('P1B 量表和预约只通过档案业务 API 并明确人工边界', () => {
  const api = source('../../src/domains/counseling/api.js')
  const workspace = source('../../src/domains/counseling/views/StudentWorkspaceView.vue')

  assert.match(api, /studentRoot\(studentId\).*\/assessments/)
  assert.match(api, /studentRoot\(studentId\).*\/appointments/)
  assert.match(workspace, /服务端按冻结的 v1 规则计分/)
  assert.match(workspace, /不会自动改变风险等级/)
  assert.match(workspace, /不会同步外部日历或发送通知/)
  assert.match(workspace, /expected_version: appointmentForm\.version/)
})

test('工作台把 UTC 时间按辅导员本地时区展示', () => {
  const displayed = formatLocalDateTime('2026-10-01T01:00:00Z', {
    timeZone: 'Asia/Shanghai',
  })
  assert.match(displayed, /09:00/)
})
