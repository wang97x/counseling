import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  resolveFrontendAccess,
  resolveFrontendRouteRedirect,
} from '../../src/utils/frontendAccess.js'

const source = (path) => readFileSync(new URL('../../src/' + path, import.meta.url), 'utf8')

test('督导是独立业务角色且只能进入授权协作入口', () => {
  const supervisor = resolveFrontendAccess('user', ['supervisor'])
  assert.equal(supervisor.defaultHome, '/collaboration')
  assert.equal(supervisor.isSupervisor, true)
  assert.equal(supervisor.canAccessCounselingCollaboration, true)
  assert.equal(supervisor.canAccessStudentRecords, false)
  assert.equal(supervisor.canAccessStudentDetail, false)
  assert.equal(supervisor.canAccessKnowledge, false)
  assert.equal(supervisor.canUseTechnicalConsole, false)
  assert.equal(resolveFrontendRouteRedirect({ requiresCounselingCollaboration: true }, supervisor), null)
  assert.equal(resolveFrontendRouteRedirect({ requiresStudentRecords: true }, supervisor), '/collaboration')
})

test('授权协作页面只调用 counseling 领域 API 并保留角色门禁', () => {
  const api = source('domains/counseling/api.js')
  const view = source('domains/counseling/views/CollaborationView.vue')
  const routes = source('router/index.js')
  const layout = source('layouts/AppLayout.vue')

  assert.match(api, /\/api\/counseling\/collaboration/)
  assert.match(api, /listSupervisionAuthorizations/)
  assert.match(api, /createExternalDelivery/)
  assert.doesNotMatch(api, /demoAdapter/)
  assert.match(view, /userStore\.businessRoles\.includes\('supervisor'\)/)
  assert.match(view, /publishSupervisionMaterial/)
  assert.match(view, /只有接收方领取后才记为已送达/)
  assert.match(routes, /name: 'CounselingCollaboration'[\s\S]*requiresCounselingCollaboration: true/)
  assert.match(layout, /canAccessCounselingCollaboration/)
})
