/** 只根据业务角色派生前端信息架构能力。 */
export function resolveFrontendAccess(_userRole, businessRoles = []) {
  const roles = new Set(Array.isArray(businessRoles) ? businessRoles : [])
  const isSuperAdmin = roles.has('super_admin')
  const isCounselor = roles.has('counselor')
  const isBusinessAdmin = roles.has('business_admin')
  const canAccessStudentRecords = isCounselor || isBusinessAdmin
  const canAccessStudentDetail = isCounselor
  const canAccessKnowledge = isCounselor || isBusinessAdmin
  const canUseTechnicalConsole = isSuperAdmin
  const canUsePlatformWorkspace = false

  return {
    isCounselor,
    isBusinessAdmin,
    isSuperAdmin,
    canAccessStudentRecords,
    canAccessStudentDetail,
    canCreateStudentRecord: isCounselor,
    canAccessKnowledge,
    canUseTechnicalConsole,
    canUsePlatformWorkspace,
    canAccessLinkedConversation: canAccessStudentDetail || canUsePlatformWorkspace,
    canManagePlatformUsers: isSuperAdmin,
    defaultHome: isSuperAdmin
      ? '/dashboard'
      : canAccessStudentRecords
        ? '/students'
        : canUseTechnicalConsole
          ? '/agent-manage'
          : '/',
  }
}

/** 校验受限角色打开的会话确实属于其有权访问的学生档案。 */
export async function resolveLinkedConversationRedirect(to, access, loadConversations) {
  if (access.canUsePlatformWorkspace) return null
  if (!access.canAccessStudentRecords) return access.defaultHome

  const studentId = String(to.query?.student_id || '')
  const workItemId = String(to.query?.work_item_id || '')
  const threadId = String(to.params?.thread_id || '')
  if (!/^[1-9]\d*$/.test(studentId) || !threadId) return access.defaultHome

  try {
    const response = await loadConversations(studentId)
    const conversations = response?.conversations || response?.items || response || []
    const matched = Array.isArray(conversations)
      ? conversations.find((item) => String(item.id) === threadId)
      : null
    if (!matched) return access.defaultHome
    const linkedWorkItemId = String(matched.work_item_id || '')
    if (linkedWorkItemId && linkedWorkItemId !== workItemId) return access.defaultHome
    if (workItemId && linkedWorkItemId !== workItemId) return access.defaultHome
    return matched
      ? null
      : access.defaultHome
  } catch {
    return access.defaultHome
  }
}

/** 统一计算一次真实路由导航的角色重定向。 */
export async function resolveFrontendNavigationRedirect(to, access, loadConversations) {
  const requirements = Object.assign({}, ...to.matched.map((record) => record.meta))
  const accessRedirect = resolveFrontendRouteRedirect(requirements, access)
  if (accessRedirect) return accessRedirect
  if (!requirements.requiresLinkedConversation) return null
  return resolveLinkedConversationRedirect(to, access, loadConversations)
}

/** 返回角色不满足页面要求时的安全落点。 */
export function resolveFrontendRouteRedirect(requirements, access) {
  if (requirements.requiresSuperAdmin && !access.canManagePlatformUsers) return access.defaultHome
  if (requirements.requiresStudentRecords && !access.canAccessStudentRecords) return access.defaultHome
  if (requirements.requiresStudentDetail && !access.canAccessStudentDetail) return access.defaultHome
  if (requirements.requiresKnowledgeManagement && !access.canAccessKnowledge) return access.defaultHome
  if (requirements.requiresExtensionsAccess && !access.canAccessKnowledge && !access.canUseTechnicalConsole) {
    return access.defaultHome
  }
  if (requirements.requiresPlatformWorkspace && !access.canUsePlatformWorkspace) return access.defaultHome
  if (requirements.requiresLinkedConversation && !access.canAccessLinkedConversation) return access.defaultHome
  if (requirements.requiresTechnicalConsole && !access.canUseTechnicalConsole) return access.defaultHome
  return null
}
