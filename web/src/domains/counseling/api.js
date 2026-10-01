import { apiGet, apiPost, apiPut } from '@/apis/base'

const root = '/api/counseling/students'
const studentRoot = (id) => `${root}/${encodeURIComponent(id)}`
const draftRoot = (studentId) => `${studentRoot(studentId)}/record-drafts`
const draftUrl = (studentId, draftId) => `${draftRoot(studentId)}/${encodeURIComponent(draftId)}`
const consultationDraftRoot = (studentId) => `${studentRoot(studentId)}/consultation-drafts`
const consultationDraftUrl = (studentId, draftId) => (
  `${consultationDraftRoot(studentId)}/${encodeURIComponent(draftId)}`
)

export const counselingApi = {
  listStudents: () => apiGet(root),
  listConversations: (id) => apiGet(`${studentRoot(id)}/conversations`),
  getDataUseNotice: () => apiGet('/api/counseling/data-use-notice'),
  acknowledgeDataUseNotice: (version) => apiPost(
    '/api/counseling/data-use-notice/acknowledgments', { version }),
  createConversation: (studentId, payload) => apiPost(`${studentRoot(studentId)}/conversations`, payload),
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
  getRecordDraft: (studentId, draftId) => apiGet(draftUrl(studentId, draftId)),
  createRecordDraft(studentId, file, requestId) {
    const body = new FormData()
    body.append('file', file)
    body.append('request_id', requestId)
    return apiPost(draftRoot(studentId), body)
  },
  updateRecordParsedText: (studentId, draftId, payload) => (
    apiPut(`${draftUrl(studentId, draftId)}/parsed-text`, payload)
  ),
  generateRecordSummary: (studentId, draftId, payload) => (
    apiPost(`${draftUrl(studentId, draftId)}/summary`, payload)
  ),
  updateRecordSummary: (studentId, draftId, payload) => (
    apiPut(`${draftUrl(studentId, draftId)}/summary`, payload)
  ),
  previewRecordArchive: (studentId, draftId, payload) => (
    apiPost(`${draftUrl(studentId, draftId)}/archive-preview`, payload)
  ),
  confirmRecordDraft: (studentId, draftId, payload) => (
    apiPost(`${draftUrl(studentId, draftId)}/confirm`, payload)
  ),
}
