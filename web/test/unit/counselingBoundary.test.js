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
  assert.doesNotMatch(api, /\/api\/chat\/thread/)
})
