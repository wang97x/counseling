import { apiGet, apiPost, apiPut } from '@/apis/base'

const root = '/api/counseling/students'
const studentRoot = (id) => `${root}/${encodeURIComponent(id)}`
const draftRoot = (studentId) => `${studentRoot(studentId)}/record-drafts`
const consultationDraftRoot = (studentId) => `${studentRoot(studentId)}/consultation-drafts`
const consultationDraftUrl = (studentId, draftId) => (
  `${consultationDraftRoot(studentId)}/${encodeURIComponent(draftId)}`
)
const collaborationRoot = '/api/counseling/collaboration'
const encoded = (value) => encodeURIComponent(value)

export const counselingApi = {
  listSupervisionAuthorizations: (studentId) => apiGet(
    `${collaborationRoot}/supervision-authorizations${studentId ? `?student_id=${encoded(studentId)}` : ''}`,
  ),
  createSupervisionAuthorization: (studentId, payload) => apiPost(
    `${collaborationRoot}/students/${encoded(studentId)}/supervision-authorizations`, payload,
  ),
  decideSupervisionAuthorization: (authorizationId, payload) => apiPost(
    `${collaborationRoot}/supervision-authorizations/${encoded(authorizationId)}/decision`, payload,
  ),
  revokeSupervisionAuthorization: (authorizationId, payload) => apiPost(
    `${collaborationRoot}/supervision-authorizations/${encoded(authorizationId)}/revoke`, payload,
  ),
  listSupervisionMaterials: (authorizationId) => apiGet(
    `${collaborationRoot}/supervision-authorizations/${encoded(authorizationId)}/materials`,
  ),
  publishSupervisionMaterial: (studentId, authorizationId, payload) => apiPost(
    `${collaborationRoot}/students/${encoded(studentId)}/supervision-authorizations/${encoded(authorizationId)}/materials`,
    payload,
  ),
  listSupervisionFeedback: (authorizationId) => apiGet(
    `${collaborationRoot}/supervision-authorizations/${encoded(authorizationId)}/feedback`,
  ),
  createSupervisionFeedback: (authorizationId, payload) => apiPost(
    `${collaborationRoot}/supervision-authorizations/${encoded(authorizationId)}/feedback`, payload,
  ),
  createSupervisionSummary: (authorizationId, payload) => apiPost(
    `${collaborationRoot}/supervision-authorizations/${encoded(authorizationId)}/summaries`, payload,
  ),
  getQualityDashboard: (window = 'quarter') => apiGet(
    `${collaborationRoot}/quality-dashboard?window=${encoded(window)}`,
  ),
  listExternalRecipients: () => apiGet(`${collaborationRoot}/external-recipients`),
  createExternalRecipient: (payload) => apiPost(`${collaborationRoot}/external-recipients`, payload),
  listExternalAuthorizations: (studentId) => apiGet(
    `${collaborationRoot}/external-authorizations${studentId ? `?student_id=${encoded(studentId)}` : ''}`,
  ),
  createExternalAuthorization: (studentId, payload) => apiPost(
    `${collaborationRoot}/students/${encoded(studentId)}/external-authorizations`, payload,
  ),
  decideExternalAuthorization: (authorizationId, payload) => apiPost(
    `${collaborationRoot}/external-authorizations/${encoded(authorizationId)}/decision`, payload,
  ),
  revokeExternalAuthorization: (authorizationId, payload) => apiPost(
    `${collaborationRoot}/external-authorizations/${encoded(authorizationId)}/revoke`, payload,
  ),
  listExternalDeliveries: (studentId) => apiGet(
    `${collaborationRoot}/students/${encoded(studentId)}/external-deliveries`,
  ),
  createExternalDelivery: (studentId, authorizationId, payload) => apiPost(
    `${collaborationRoot}/students/${encoded(studentId)}/external-authorizations/${encoded(authorizationId)}/deliveries`,
    payload,
  ),
  retryExternalDelivery: (deliveryId, payload) => apiPost(
    `${collaborationRoot}/external-deliveries/${encoded(deliveryId)}/retry`, payload,
  ),
  withdrawExternalDelivery: (deliveryId, payload) => apiPost(
    `${collaborationRoot}/external-deliveries/${encoded(deliveryId)}/withdraw`, payload,
  ),
  listStudents: () => apiGet(root),
  listScales: () => apiGet(`${root}/scales`),
  listAssessments: (studentId) => apiGet(`${studentRoot(studentId)}/assessments`),
  createAssessment: (studentId, payload) => apiPost(
    `${studentRoot(studentId)}/assessments`, payload,
  ),
  listAppointments: (studentId) => apiGet(`${studentRoot(studentId)}/appointments`),
  createAppointment: (studentId, payload) => apiPost(
    `${studentRoot(studentId)}/appointments`, payload,
  ),
  updateAppointment: (studentId, appointmentId, payload) => apiPut(
    `${studentRoot(studentId)}/appointments/${encodeURIComponent(appointmentId)}`, payload,
  ),
  listPlans: (studentId) => apiGet(`${studentRoot(studentId)}/plans`),
  createPlan: (studentId, payload) => apiPost(`${studentRoot(studentId)}/plans`, payload),
  listCrisisCases: (studentId) => apiGet(`${studentRoot(studentId)}/crisis-cases`),
  createCrisisCase: (studentId, payload) => apiPost(
    `${studentRoot(studentId)}/crisis-cases`, payload,
  ),
  appendCrisisCaseEvent: (studentId, caseId, payload) => apiPost(
    `${studentRoot(studentId)}/crisis-cases/${encodeURIComponent(caseId)}/events`, payload,
  ),
  listReferrals: (studentId) => apiGet(`${studentRoot(studentId)}/referrals`),
  createReferral: (studentId, payload) => apiPost(
    `${studentRoot(studentId)}/referrals`, payload,
  ),
  completeReferralFollowUp: (studentId, referralId, payload) => apiPost(
    `${studentRoot(studentId)}/referrals/${encodeURIComponent(referralId)}/follow-up`, payload,
  ),
  listRiskHints: (studentId) => apiGet(`${studentRoot(studentId)}/risk-hints`),
  createRiskHint: (studentId, payload) => apiPost(`${studentRoot(studentId)}/risk-hints`, payload),
  reviewRiskHint: (studentId, hintId, payload) => apiPost(
    `${studentRoot(studentId)}/risk-hints/${encodeURIComponent(hintId)}/review`, payload,
  ),
  listRiskHintEvaluations: () => apiGet('/api/counseling/admin/risk-hint-evaluations'),
  publishRiskHintEvaluation: (payload) => apiPost(
    '/api/counseling/admin/risk-hint-evaluations', payload,
  ),
  listCrisisProtocols: () => apiGet('/api/counseling/admin/crisis-protocols'),
  publishCrisisProtocol: (payload) => apiPost(
    '/api/counseling/admin/crisis-protocols', payload,
  ),
  listDepartmentReferrals: () => apiGet('/api/counseling/admin/referrals'),
  decideReferral: (referralId, payload) => apiPost(
    `/api/counseling/admin/referrals/${encodeURIComponent(referralId)}/decision`, payload,
  ),
  updateAppointmentStatus: (studentId, appointmentId, payload) => apiPost(
    `${studentRoot(studentId)}/appointments/${encodeURIComponent(appointmentId)}/status`, payload,
  ),
  listConversations: (id) => apiGet(`${studentRoot(id)}/conversations`),
  getDataUseNotice: () => apiGet('/api/counseling/data-use-notice'),
  acknowledgeDataUseNotice: (version) => apiPost(
    '/api/counseling/data-use-notice/acknowledgments', { version }),
  createAIWorkItem: (studentId, payload) => apiPost(`${studentRoot(studentId)}/ai-work-items`, payload),
  preflightMaterial: (studentId, workItemId, payload) => apiPost(
    `${studentRoot(studentId)}/ai-work-items/${encodeURIComponent(workItemId)}/materials/preflight`,
    payload,
  ),
  importMaterial: (studentId, workItemId, payload) => apiPost(
    `${studentRoot(studentId)}/ai-work-items/${encodeURIComponent(workItemId)}/materials/import`,
    payload,
  ),
  listMaterials: (studentId) => apiGet(`${studentRoot(studentId)}/materials`),
  materialContentUrl: (studentId, materialId, mode = 'preview') => (
    `${studentRoot(studentId)}/materials/${encodeURIComponent(materialId)}/content?mode=${encodeURIComponent(mode)}`
  ),
  getMaterialContent: (studentId, materialId, mode = 'preview') => apiGet(
    `${studentRoot(studentId)}/materials/${encodeURIComponent(materialId)}/content?mode=${encodeURIComponent(mode)}`,
    {}, true, 'blob'),
  confirmMaterial: (studentId, materialId, payload) => apiPost(
    `${studentRoot(studentId)}/materials/${encodeURIComponent(materialId)}/confirm`, payload,
  ),
  rejectMaterial: (studentId, materialId, payload) => apiPost(
    `${studentRoot(studentId)}/materials/${encodeURIComponent(materialId)}/reject`, payload,
  ),
  getStudent: (id) => apiGet(studentRoot(id)),
  createStudent: (payload) => apiPost(root, payload),
  updateStudent: (id, payload) => apiPut(studentRoot(id), payload),
  closeStudent: (id, payload) => apiPost(`${studentRoot(id)}/close`, payload),
  getTimeline: (id) => apiGet(`${studentRoot(id)}/timeline`),
  createManualRecordDraft: (studentId, payload) => apiPost(consultationDraftRoot(studentId), payload),
  updateManualRecordDraft: (studentId, draftId, payload) => (
    apiPut(consultationDraftUrl(studentId, draftId), payload)
  ),
  confirmManualRecord: (studentId, draftId, payload) => (
    apiPost(`${consultationDraftUrl(studentId, draftId)}/confirm`, payload)
  ),
  addRecordCorrection: (studentId, recordId, payload) => (
    apiPost(`${studentRoot(studentId)}/records/${encodeURIComponent(recordId)}/corrections`, payload)
  ),
  listRiskEvents: (studentId) => apiGet(`${studentRoot(studentId)}/risk-events`),
  createRiskEvent: (studentId, payload) => apiPost(`${studentRoot(studentId)}/risk-events`, payload),
  getDepartmentSummary: () => apiGet('/api/counseling/admin/summary'),
  listRecordDrafts: (studentId) => apiGet(draftRoot(studentId)),
}
