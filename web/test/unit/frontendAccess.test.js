import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  resolveFrontendAccess,
  resolveFrontendNavigationRedirect,
  resolveFrontendRouteRedirect,
  resolveLinkedConversationRedirect,
} from '../../src/utils/frontendAccess.js'

const source = (path) => readFileSync(new URL('../../src/' + path, import.meta.url), 'utf8')

test('三类产品角色获得约定首页和前端模块能力', () => {
  const counselor = resolveFrontendAccess('user', ['counselor'])
  assert.equal(counselor.defaultHome, '/students')
  assert.equal(counselor.canAccessStudentRecords, true)
  assert.equal(counselor.canCreateStudentRecord, true)
  assert.equal(counselor.canAccessKnowledge, true)
  assert.equal(counselor.canUseTechnicalConsole, false)
  assert.equal(counselor.canUsePlatformWorkspace, false)

  const businessAdmin = resolveFrontendAccess('user', ['business_admin'])
  assert.equal(businessAdmin.defaultHome, '/students')
  assert.equal(businessAdmin.canAccessStudentRecords, true)
  assert.equal(businessAdmin.canAccessStudentDetail, false)
  assert.equal(businessAdmin.canCreateStudentRecord, false)
  assert.equal(businessAdmin.canUseTechnicalConsole, false)
  assert.equal(businessAdmin.canUsePlatformWorkspace, false)
  assert.equal(businessAdmin.canAccessLinkedConversation, false)

  const superAdmin = resolveFrontendAccess('superadmin', [])
  assert.equal(superAdmin.defaultHome, '/dashboard')
  assert.equal(superAdmin.canUseTechnicalConsole, true)
  assert.equal(superAdmin.canUsePlatformWorkspace, false)
  assert.equal(superAdmin.canManagePlatformUsers, true)
})

test('辅导员直接访问技术或平台工作区会回到档案首页，档案关联会话保持可用', () => {
  const counselor = resolveFrontendAccess('user', ['counselor'])
  assert.equal(
    resolveFrontendRouteRedirect({ requiresTechnicalConsole: true }, counselor),
    '/students',
  )
  assert.equal(
    resolveFrontendRouteRedirect({ requiresPlatformWorkspace: true }, counselor),
    '/students',
  )
  assert.equal(resolveFrontendRouteRedirect({ requiresLinkedConversation: true }, counselor), null)
  assert.equal(resolveFrontendRouteRedirect({ requiresStudentRecords: true }, counselor), null)
  assert.equal(resolveFrontendRouteRedirect({}, counselor), null)

  const routes = source('router/index.js')
  assert.match(routes, /name: 'StudentRecords'[\s\S]*?requiresStudentRecords: true/)
  assert.match(routes, /name: 'StudentRecordDetail'[\s\S]*?requiresStudentDetail: true/)
  assert.match(routes, /name: 'AgentComp'[\s\S]*?requiresPlatformWorkspace: true/)
  assert.match(routes, /name: 'AgentCompWithThreadId'[\s\S]*?requiresLinkedConversation: true/)
  assert.match(routes, /resolveFrontendNavigationRedirect\([\s\S]*?counselingApi\.listConversations/)
  assert.match(routes, /name: 'CLIAuthAuthorize'[\s\S]*?requiresPlatformWorkspace: true/)
})

test('未知业务用户不能继承档案或技术入口，无业务角色的平台管理员保留原控制台', () => {
  const unknown = resolveFrontendAccess('user', [])
  assert.equal(unknown.defaultHome, '/')
  assert.equal(unknown.canAccessStudentRecords, false)
  assert.equal(unknown.canUseTechnicalConsole, false)
  assert.equal(
    resolveFrontendRouteRedirect({ requiresLinkedConversation: true }, unknown),
    '/',
  )

  const legacyAdmin = resolveFrontendAccess('admin', [])
  assert.equal(legacyAdmin.defaultHome, '/agent-manage')
  assert.equal(legacyAdmin.canUseTechnicalConsole, true)
  assert.equal(legacyAdmin.canUsePlatformWorkspace, true)

  const legacyTechnicalAdmin = resolveFrontendAccess('user', ['technical_admin'])
  assert.equal(legacyTechnicalAdmin.defaultHome, '/agent-manage')
  assert.equal(legacyTechnicalAdmin.canUseTechnicalConsole, true)
  assert.equal(legacyTechnicalAdmin.canUsePlatformWorkspace, false)
})

test('档案角色只能打开后端确认属于该档案的关联会话', async () => {
  const counselor = resolveFrontendAccess('user', ['counselor'])
  const linkedRoute = { params: { thread_id: 'thread-linked' }, query: { student_id: '23' } }
  const unrelatedRoute = { params: { thread_id: 'thread-other' }, query: { student_id: '23' } }
  const missingStudentRoute = { params: { thread_id: 'thread-linked' }, query: {} }
  const loadConversations = async (studentId) => {
    assert.equal(studentId, '23')
    return [{ id: 'thread-linked' }]
  }

  assert.equal(
    await resolveLinkedConversationRedirect(linkedRoute, counselor, loadConversations),
    null,
  )
  assert.equal(
    await resolveLinkedConversationRedirect(unrelatedRoute, counselor, loadConversations),
    '/students',
  )
  assert.equal(
    await resolveLinkedConversationRedirect(missingStudentRoute, counselor, loadConversations),
    '/students',
  )
  assert.equal(
    await resolveLinkedConversationRedirect(linkedRoute, counselor, async () => {
      throw new Error('forbidden')
    }),
    '/students',
  )

  const platformAdmin = resolveFrontendAccess('admin', [])
  assert.equal(
    await resolveLinkedConversationRedirect(unrelatedRoute, platformAdmin, async () => {
      throw new Error('should not load')
    }),
    null,
  )
})

test('真实路由导航拒绝角色不可见页面和非档案关联会话', async () => {
  const counselor = resolveFrontendAccess('user', ['counselor'])
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/students', component: {} },
      { path: '/agent-manage', component: {}, meta: { requiresTechnicalConsole: true } },
      { path: '/auth/cli/authorize', component: {}, meta: { requiresPlatformWorkspace: true } },
      { path: '/agent/:thread_id', component: {}, meta: { requiresLinkedConversation: true } },
      { path: '/extensions/mcp/:slug', component: {}, meta: { requiresTechnicalConsole: true } },
      { path: '/extensions/skill/:slug', component: {}, meta: { requiresTechnicalConsole: true } },
    ],
  })
  router.beforeEach(async (to) => {
    return (
      (await resolveFrontendNavigationRedirect(to, counselor, async () => [
        { id: 'thread-linked' },
      ])) || true
    )
  })

  await router.push('/agent-manage')
  assert.equal(router.currentRoute.value.fullPath, '/students')
  await router.push('/auth/cli/authorize')
  assert.equal(router.currentRoute.value.fullPath, '/students')
  await router.push('/extensions/mcp/example')
  assert.equal(router.currentRoute.value.fullPath, '/students')
  await router.push('/extensions/skill/example')
  assert.equal(router.currentRoute.value.fullPath, '/students')
  await router.push('/agent/thread-other?student_id=23')
  assert.equal(router.currentRoute.value.fullPath, '/students')
  await router.push('/agent/thread-linked?student_id=23')
  assert.equal(router.currentRoute.value.fullPath, '/agent/thread-linked?student_id=23')
})

test('业务管理员不能用直接 URL 进入技术控制台、通用聊天或个人空间', () => {
  const businessAdmin = resolveFrontendAccess('user', ['business_admin'])
  assert.equal(
    resolveFrontendRouteRedirect({ requiresPlatformWorkspace: true }, businessAdmin),
    '/students',
  )
  assert.equal(
    resolveFrontendRouteRedirect({ requiresTechnicalConsole: true }, businessAdmin),
    '/students',
  )
  assert.equal(
    resolveFrontendRouteRedirect({ requiresStudentDetail: true }, businessAdmin),
    '/students',
  )
  assert.equal(
    resolveFrontendRouteRedirect({ requiresLinkedConversation: true }, businessAdmin),
    '/students',
  )

  const migratedBusinessAdmin = resolveFrontendAccess('admin', ['business_admin'])
  assert.equal(migratedBusinessAdmin.canUseTechnicalConsole, false)
  assert.equal(migratedBusinessAdmin.canUsePlatformWorkspace, false)
  assert.equal(
    resolveFrontendRouteRedirect({ requiresPlatformWorkspace: true }, migratedBusinessAdmin),
    '/students',
  )
})

test('超级管理员保留技术管理，但不能进入通用聊天或个人空间', () => {
  const superAdmin = resolveFrontendAccess('superadmin', [])
  assert.equal(superAdmin.canUseTechnicalConsole, true)
  assert.equal(
    resolveFrontendRouteRedirect({ requiresPlatformWorkspace: true }, superAdmin),
    '/dashboard',
  )
  assert.equal(
    resolveFrontendRouteRedirect({ requiresLinkedConversation: true }, superAdmin),
    '/dashboard',
  )
})

test('业务管理员真实路由只能进入档案列表，不能进入详情或关联会话', async () => {
  const businessAdmin = resolveFrontendAccess('user', ['business_admin'])
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/students', component: {}, meta: { requiresStudentRecords: true } },
      { path: '/students/:studentId', component: {}, meta: { requiresStudentDetail: true } },
      { path: '/agent/:thread_id', component: {}, meta: { requiresLinkedConversation: true } },
    ],
  })
  router.beforeEach(async (to) => {
    return (await resolveFrontendNavigationRedirect(to, businessAdmin, async () => {
      throw new Error('不应读取个案会话')
    })) || true
  })

  await router.push('/students/23')
  assert.equal(router.currentRoute.value.fullPath, '/students')
  await router.push('/agent/thread-linked?student_id=23')
  assert.equal(router.currentRoute.value.fullPath, '/students')
})

test('导航与设置消费统一前端能力，不再直接向辅导员开放技术模块', () => {
  const layout = source('layouts/AppLayout.vue')
  const extensions = source('views/ExtensionsView.vue')
  const settings = source('components/SettingsModal.vue')
  const login = source('views/LoginView.vue')
  const oidc = source('views/OIDCCallbackView.vue')
  const studentWorkspace = source('domains/counseling/views/StudentWorkspaceView.vue')

  assert.match(layout, /userStore\.canAccessStudentRecords/)
  assert.match(layout, /userStore\.canUseTechnicalConsole/)
  assert.match(layout, /userStore\.canUsePlatformWorkspace && !sidebarCollapsed/)
  assert.match(layout, /if \(userStore\.canUsePlatformWorkspace\)/)
  assert.match(extensions, /userStore\.canUseTechnicalConsole/)
  assert.doesNotMatch(extensions, /const userExtensionTabs/)
  assert.match(settings, /if \(userStore\.isLoggedIn\) tabs\.push\('account'\)/)
  assert.match(settings, /if \(userStore\.canUseTechnicalConsole\) tabs\.push\('apiKeys', 'agentEnv', 'base', 'ocr'\)/)
  assert.match(login, /router\.push\(userStore\.defaultHome\)/)
  assert.match(oidc, /router\.push\(userStore\.defaultHome\)/)
  assert.equal((studentWorkspace.match(/query: \{ student_id:/g) || []).length, 0)
  assert.doesNotMatch(studentWorkspace, /打开下一步助手|openConversationCreator/)
})
