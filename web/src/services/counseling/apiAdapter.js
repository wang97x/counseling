import { counselingApi } from '../../apis/counseling_api.js'
import { threadApi } from '../../apis/agent_api.js'
import { filterApiStudents, mapApiStudent, toApiStudentPatch } from './apiMapping.js'
import { validateCounselingUpload } from './uploadValidation.js'

const unsupported = (capability) => ({
  status: 'not_supported',
  capability,
  message: '后端能力尚未接入',
})

/** 创建真实接口适配器；缺失能力不会回退到演示数据。 */
export function createCounselingApiAdapter() {
  return {
    mode: 'api',

    async listCounselors() {
      return { status: 'ok', data: await counselingApi.listCounselors() }
    },

    async createStudent(payload) {
      return { status: 'ok', data: await counselingApi.createStudent(payload) }
    },

    async createConversation(payload) {
      return { status: 'ok', data: await counselingApi.createConversation(payload) }
    },

    async listStudents(filters = {}) {
      const response = await counselingApi.listStudents({
        skip: 0,
        limit: 100,
        search: filters.query || undefined,
        status: filters.status || undefined,
      })
      const items = (response?.students || response?.items || response || []).map(mapApiStudent)
      return { status: 'ok', data: filterApiStudents(items, filters) }
    },

    async getWorkspace(studentId) {
      const [detail, conversations] = await Promise.all([
        counselingApi.getStudent(studentId),
        counselingApi.listConversations(studentId, { limit: 100 }),
      ])
      const items = conversations?.conversations || conversations?.items || conversations || []
      return {
        status: 'ok',
        data: {
          student: mapApiStudent({ ...detail, conversation_count: items.length }),
          background: detail.background_summary || detail.notes || '尚未录入背景信息',
          todos: [],
          timeline: items.map((item) => ({
            id: String(item.id),
            occurredAt: item.created_at || '',
            title: item.title || '辅导会话',
            summary: item.summary || '暂无摘要',
            source: 'manual',
          })),
          goals: [],
          assessments: [],
          crises: [],
          uploads: [],
          assistantMessages: [],
        },
      }
    },

    async updateStudent(studentId, patch) {
      await counselingApi.updateStudent(studentId, toApiStudentPatch(patch))
      return this.getWorkspace(studentId)
    },

    async uploadRecord(studentId, file, { threadId } = {}) {
      const validationError = validateCounselingUpload(file)
      if (validationError) return validationError
      if (!threadId) return unsupported('record_upload_requires_thread')
      const uploaded = await threadApi.uploadTmpAttachment(file)
      let parsedObjectName = null
      const parseMethod = uploaded.parse_supported ? uploaded.parse_methods?.[0] : null
      if (parseMethod) {
        const parsed = await threadApi.parseTmpAttachment({
          object_name: uploaded.object_name,
          parse_method: parseMethod,
        })
        parsedObjectName = parsed.parsed_object_name
      }
      await threadApi.confirmTmpThreadAttachments(threadId, [{
        file_type: uploaded.file_type,
        object_name: uploaded.object_name,
        parsed_object_name: parsedObjectName,
      }])
      return {
        status: 'ok',
        data: {
          id: String(uploaded.object_name),
          name: uploaded.file_name || file.name,
          size: uploaded.file_size || file.size,
          type: uploaded.file_type || file.name.split('.').pop().toLowerCase(),
          status: 'parsed',
          parsedPreview: '文件已交由现有附件解析流程处理。',
          createdAt: new Date().toISOString(),
        },
      }
    },

    async generateSummary() { return unsupported('summary_generation') },
    async saveDraft() { return unsupported('summary_draft') },
    async buildArchivePreview() { return unsupported('archive_preview') },
    async archiveSummary() { return unsupported('archive') },
    async sendAssistantMessage() { return unsupported('counseling_assistant') },
    async resetDemo() { return unsupported('demo_reset') },
  }
}
