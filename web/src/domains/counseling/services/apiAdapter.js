import { counselingApi } from '../api.js'
import {
  filterApiStudents,
  mapApiRecordDraft,
  mapApiStudent,
  mapApiTimelineNode,
  toApiStudentPatch,
} from './apiMapping.js'

/** 创建真实接口适配器；缺失能力不会回退到演示数据。 */
export function createCounselingApiAdapter() {
  return {
    async createStudent(payload) {
      return { status: 'ok', data: await counselingApi.createStudent(payload) }
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
      const [
        detail, timeline, drafts, materials, scales, assessments, appointments,
        plans, crisisCases, referrals, riskHints,
      ] = await Promise.all([
        counselingApi.getStudent(studentId), counselingApi.getTimeline(studentId),
        counselingApi.listRecordDrafts(studentId), counselingApi.listMaterials(studentId),
        counselingApi.listScales(), counselingApi.listAssessments(studentId),
        counselingApi.listAppointments(studentId), counselingApi.listPlans(studentId),
        counselingApi.listCrisisCases(studentId), counselingApi.listReferrals(studentId),
        counselingApi.listRiskHints(studentId),
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
          scales: scales?.items || scales || [], assessments: assessments?.items || assessments || [],
          appointments: appointments?.items || appointments || [], plans: plans?.items || plans || [],
          crisisCases: crisisCases?.items || crisisCases || [],
          referrals: referrals?.items || referrals || [],
          riskHints: riskHints?.items || riskHints || [],
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

    async createAssessment(studentId, payload) {
      return { status: 'ok', data: await counselingApi.createAssessment(studentId, payload) }
    },

    async createAppointment(studentId, payload) {
      return { status: 'ok', data: await counselingApi.createAppointment(studentId, payload) }
    },

    async updateAppointment(studentId, appointmentId, payload) {
      return {
        status: 'ok',
        data: await counselingApi.updateAppointment(studentId, appointmentId, payload),
      }
    },

    async updateAppointmentStatus(studentId, appointmentId, expectedVersion, status) {
      return {
        status: 'ok',
        data: await counselingApi.updateAppointmentStatus(studentId, appointmentId, {
          expected_version: expectedVersion,
          status,
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

    async createPlan(studentId, payload) {
      return { status: 'ok', data: await counselingApi.createPlan(studentId, payload) }
    },

    async createCrisisCase(studentId, payload) {
      return { status: 'ok', data: await counselingApi.createCrisisCase(studentId, payload) }
    },

    async appendCrisisCaseEvent(studentId, caseId, payload) {
      return {
        status: 'ok',
        data: await counselingApi.appendCrisisCaseEvent(studentId, caseId, payload),
      }
    },

    async createReferral(studentId, payload) {
      return { status: 'ok', data: await counselingApi.createReferral(studentId, payload) }
    },

    async completeReferralFollowUp(studentId, referralId, payload) {
      return {
        status: 'ok',
        data: await counselingApi.completeReferralFollowUp(studentId, referralId, payload),
      }
    },

    async listCrisisProtocols() {
      return { status: 'ok', data: await counselingApi.listCrisisProtocols() }
    },

    async publishCrisisProtocol(payload) {
      return { status: 'ok', data: await counselingApi.publishCrisisProtocol(payload) }
    },

    async listDepartmentReferrals() {
      return { status: 'ok', data: await counselingApi.listDepartmentReferrals() }
    },

    async decideReferral(referralId, payload) {
      return { status: 'ok', data: await counselingApi.decideReferral(referralId, payload) }
    },

    async createRiskHint(studentId, payload) {
      return { status: 'ok', data: await counselingApi.createRiskHint(studentId, payload) }
    },

    async reviewRiskHint(studentId, hintId, payload) {
      return {
        status: 'ok',
        data: await counselingApi.reviewRiskHint(studentId, hintId, payload),
      }
    },

    async listRiskHintEvaluations() {
      return { status: 'ok', data: await counselingApi.listRiskHintEvaluations() }
    },

    async publishRiskHintEvaluation(payload) {
      return {
        status: 'ok',
        data: await counselingApi.publishRiskHintEvaluation(payload),
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
