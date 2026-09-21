/** 将现有学生接口模型映射为工作台可见摘要。 */
export function mapApiStudent(item) {
  const code = item.student_code || item.student_no || '未设置'
  return {
    id: String(item.id),
    code,
    name: item.name || item.display_name || '学生 ' + code,
    chiefConcern: item.background_summary !== undefined
      ? item.background_summary || '尚未录入主诉'
      : item.notes || '打开档案查看',
    riskLevel: 'unknown',
    status: item.status === 'closed' ? 'closed' : 'active',
    sessionCount: item.conversation_count == null ? null : Number(item.conversation_count),
    nextAppointment: undefined,
    recentActivity: item.updated_at ? '档案更新于 ' + item.updated_at.slice(0, 10) : '动态仅负责人可查看',
    counselorId: item.counselor_id == null ? null : Number(item.counselor_id),
    counselor: item.counselor_name || item.counselor_username || (item.counselor_id ? '负责人 #' + item.counselor_id : '未分配'),
  }
}

/** 将档案关联会话映射为可继续的时间轴节点。 */
export function mapApiConversation(item) {
  return {
    id: String(item.id),
    conversationId: String(item.id),
    occurredAt: item.created_at || '',
    title: item.title || '辅导会话',
    summary: item.summary || '暂无摘要',
    source: 'assistant',
  }
}

/** 在当前列表接口不支持查询参数时执行前端可见筛选。 */
export function filterApiStudents(items, filters = {}) {
  const query = String(filters.query || '').trim().toLowerCase()
  return items
    .filter((item) => !query || [item.code, item.counselor]
      .some((value) => String(value).toLowerCase().includes(query)))
    .filter((item) => !filters.riskLevel || item.riskLevel === filters.riskLevel)
    .filter((item) => !filters.status || item.status === filters.status)
    .filter((item) => filters.appointment !== 'upcoming' || item.nextAppointment)
}

/** 将工作台可编辑字段收敛为现有更新接口契约。 */
export function toApiStudentPatch(patch) {
  const payload = {}
  if (patch.chiefConcern !== undefined) payload.background_summary = patch.chiefConcern
  if (patch.status !== undefined) payload.status = patch.status === 'closed' ? 'closed' : 'active'
  return payload
}
