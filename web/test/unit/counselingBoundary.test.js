import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

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

test('档案会话通过业务 API 创建而不直连通用线程入口', () => {
  const api = source('../../src/domains/counseling/api.js')

  assert.match(api, /studentRoot\(studentId\).*\/conversations/)
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
