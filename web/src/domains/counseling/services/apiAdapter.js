import { counselingApi } from '../api.js'
import {
  filterApiStudents,
  mapApiRecordDraft,
  mapApiStudent,
  mapApiTimelineNode,
  toApiStudentPatch,
} from './apiMapping.js'
import { validateCounselingUpload } from './uploadValidation.js'

/** 创建真实接口适配器；缺失能力不会回退到演示数据。 */
export function createCounselingApiAdapter() {
  return {
    mode: 'api',

    async createStudent(payload) {
      return { status: 'ok', data: await counselingApi.createStudent(payload) }
    },

    async createConversation(payload) {
      const { student_id: studentId, ...request } = payload
      return { status: 'ok', data: await counselingApi.createConversation(studentId, request) }
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
      const [detail, timeline, drafts, materials] = await Promise.all([
        counselingApi.getStudent(studentId),
        counselingApi.getTimeline(studentId),
        counselingApi.listRecordDrafts(studentId),
        counselingApi.listMaterials(studentId),
      ])
      const items = timeline?.timeline || timeline?.items || timeline || []
      const draftItems = drafts?.drafts || drafts?.items || drafts || []
      return {
        status: 'ok',
        data: {
          student: mapApiStudent(detail),
          background: detail.background_summary || detail.notes || '尚未录入背景信息',
          timeline: items.map(mapApiTimelineNode),
          drafts: draftItems.map(mapApiRecordDraft)
            .filter((item) => item.recordKind === 'manual' && item.status === 'draft'),
          materials: materials?.materials || materials?.items || materials || [],
        },
      }
    },

    async updateStudent(studentId, patch) {
      await counselingApi.updateStudent(studentId, toApiStudentPatch(patch))
      return this.getWorkspace(studentId)
    },

    async closeStudent(studentId, expectedVersion, closureNote) {
      return {
        status: 'ok',
        data: await counselingApi.closeStudent(studentId, {
          expected_version: expectedVersion,
          closure_note: closureNote,
        }),
      }
    },

    async createManualRecordDraft(studentId, payload) {
      const data = await counselingApi.createManualRecordDraft(studentId, payload)
      return { status: 'ok', data: mapApiRecordDraft(data) }
    },

    async updateManualRecordDraft(studentId, draftId, payload) {
      const data = await counselingApi.updateManualRecordDraft(studentId, draftId, payload)
      return { status: 'ok', data: mapApiRecordDraft(data) }
    },

    async confirmManualRecord(studentId, draftId, expectedVersion, confirmationKey) {
      return {
        status: 'ok',
        data: await counselingApi.confirmManualRecord(studentId, draftId, {
          expected_version: expectedVersion,
          confirmation_key: confirmationKey,
        }),
      }
    },

    async addRecordCorrection(studentId, recordId, payload) {
      return { status: 'ok', data: await counselingApi.addRecordCorrection(studentId, recordId, payload) }
    },

    async createRiskEvent(studentId, payload) {
      return { status: 'ok', data: await counselingApi.createRiskEvent(studentId, payload) }
    },

    async getDepartmentSummary() {
      return { status: 'ok', data: await counselingApi.getDepartmentSummary() }
    },

    async createRecordDraft(studentId, file, requestId) {
      const validationError = validateCounselingUpload(file)
      if (validationError) return validationError
      return { status: 'ok', data: mapApiRecordDraft(await counselingApi.createRecordDraft(studentId, file, requestId)) }
    },

    async listRecordDrafts(studentId) {
      const response = await counselingApi.listRecordDrafts(studentId)
      const items = response?.drafts || response?.items || response || []
      return { status: 'ok', data: items.map(mapApiRecordDraft) }
    },

    async updateParsedText(studentId, draftId, expectedVersion, parsedText) {
      const data = await counselingApi.updateRecordParsedText(studentId, draftId, {
        expected_version: expectedVersion,
        parsed_text: parsedText,
      })
      return { status: 'ok', data: mapApiRecordDraft(data) }
    },

    async generateSummary(studentId, draftId, expectedVersion, requestId) {
      const data = await counselingApi.generateRecordSummary(studentId, draftId, {
        expected_version: expectedVersion,
        request_id: requestId,
      })
      return { status: 'ok', data: mapApiRecordDraft(data) }
    },

    async updateSummary(studentId, draftId, expectedVersion, summary) {
      const data = await counselingApi.updateRecordSummary(studentId, draftId, {
        expected_version: expectedVersion,
        summary: {
          schema_version: 1,
          sections: summary.sections.map(({ title, content }) => ({ title, content })),
        },
      })
      return { status: 'ok', data: mapApiRecordDraft(data) }
    },

    async buildArchivePreview(studentId, draftId, expectedVersion) {
      return {
        status: 'ok',
        data: await counselingApi.previewRecordArchive(studentId, draftId, {
          expected_version: expectedVersion,
        }),
      }
    },

    async confirmRecordDraft(studentId, draftId, expectedVersion, confirmationKey) {
      return {
        status: 'ok',
        data: await counselingApi.confirmRecordDraft(studentId, draftId, {
          expected_version: expectedVersion,
          confirmation_key: confirmationKey,
        }),
      }
    },

    async createAIWorkItem(studentId, instruction, requestId) {
      return {
        status: 'ok',
        data: await counselingApi.createAIWorkItem(studentId, {
          request_id: requestId,
          instruction,
        }),
      }
    },

    async confirmMaterial(studentId, materialId, confirmationKey) {
      const data = await counselingApi.confirmMaterial(studentId, materialId, {
        confirmation_key: confirmationKey,
      })
      return { status: 'ok', data }
    },

    async rejectMaterial(studentId, materialId, requestId) {
      const data = await counselingApi.rejectMaterial(studentId, materialId, {
        request_id: requestId,
      })
      return { status: 'ok', data }
    },

    async getMaterialContent(studentId, materialId, mode) {
      return counselingApi.getMaterialContent(studentId, materialId, mode)
    },
  }
}
