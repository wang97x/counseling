/** 将现有学生接口模型映射为工作台可见摘要。 */
export function mapApiStudent(item) {
  const code = item.student_code || item.student_no || '未设置'
  return {
    id: String(item.id),
    code,
    name: item.name || item.display_name || '学生 ' + code,
    className: item.class_name || '',
    chiefConcern: item.background_summary !== undefined
      ? item.background_summary || '尚未录入主诉'
      : item.notes || '打开档案查看',
    riskLevel: ['normal', 'watch', 'urgent'].includes(item.current_risk_level)
      ? item.current_risk_level
      : 'unknown',
    status: item.status === 'closed' ? 'closed' : 'active',
    sessionCount: item.conversation_count == null ? null : Number(item.conversation_count),
    recentActivity: item.updated_at ? '档案更新于 ' + item.updated_at.slice(0, 10) : '动态仅负责人可查看',
    counselorId: item.counselor_id == null ? null : Number(item.counselor_id),
    counselor: item.counselor_name || item.counselor_username || (item.counselor_id ? '负责人 #' + item.counselor_id : '未分配'),
    version: Number(item.version || 1),
    closureNote: item.closure_note || '',
    closedAt: item.closed_at || '',
  }
}

/** 将统一时间线接口节点映射为工作台展示模型。 */
export function mapApiTimelineNode(item) {
  const conversationId = item.conversation_id
    ?? item.thread_id
    ?? (item.type === 'conversation' ? item.id : undefined)
  const sections = Array.isArray(item.summary?.sections) ? item.summary.sections : []
  const content = item.content && typeof item.content === 'object' ? item.content : null
  const summary = sections.length
    ? sections.map((section) => `${section.title}：${section.content}`).join('\n')
    : item.type === 'risk_event'
      ? item.summary || '已记录人工风险事件'
      : content?.overview || item.summary || (typeof item.content === 'string' ? item.content : '') || '暂无摘要'
  return {
    id: String(item.id),
    conversationId: conversationId == null ? undefined : String(conversationId),
    occurredAt: item.occurred_at || item.created_at || '',
    title: item.title || '档案记录',
    summary,
    type: item.type || 'record',
    source: item.type === 'conversation'
      ? 'assistant'
      : item.type === 'risk_event'
        ? 'risk'
        : item.type === 'record_correction'
          ? 'correction'
          : item.type === 'consultation_record'
            ? 'manual'
            : 'upload',
    content,
    recordId: item.record_id == null ? undefined : String(item.record_id),
    riskLevel: item.risk_level,
    riskStatus: item.risk_status,
  }
}

/** 规范化服务端档案草稿，避免组件依赖 snake_case wire 字段。 */
export function mapApiRecordDraft(item) {
  const source = item?.source || {}
  const summary = item?.summary || { schema_version: 1, sections: [] }
  return {
    id: String(item?.id || ''),
    studentId: String(item?.student_id || ''),
    status: item?.status || 'parsed',
    version: Number(item?.version || 0),
    recordKind: item?.record_kind || 'file',
    consultedAt: item?.consulted_at || '',
    consultationType: item?.consultation_type || '',
    content: item?.content || null,
    source: {
      fileName: source.file_name || '',
      fileType: source.file_type || '',
      fileSize: Number(source.file_size || 0),
    },
    parsedText: item?.parsed_text || '',
    summary: {
      schemaVersion: Number(summary.schema_version || 1),
      sections: Array.isArray(summary.sections)
        ? summary.sections.map((section) => ({
          title: String(section?.title || ''),
          content: String(section?.content || ''),
        }))
        : [],
    },
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
}

/** 将工作台可编辑字段收敛为现有更新接口契约。 */
export function toApiStudentPatch(patch) {
  const payload = {}
  if (patch.chiefConcern !== undefined) payload.background_summary = patch.chiefConcern
  if (patch.displayName !== undefined) payload.display_name = patch.displayName
  if (patch.className !== undefined) payload.class_name = patch.className
  return payload
}
