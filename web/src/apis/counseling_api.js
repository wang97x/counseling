import { apiGet, apiPost, apiPut } from './base'

const root = '/api/counseling/students'

export const counselingApi = {
  listStudents: () => apiGet(root),
  listConversations: (id) => apiGet(`${root}/${encodeURIComponent(id)}/conversations`),
  createConversation: (payload) => apiPost('/api/chat/thread', payload),
  getStudent: (id) => apiGet(`${root}/${encodeURIComponent(id)}`),
  createStudent: (payload) => apiPost(root, payload),
  updateStudent: (id, payload) => apiPut(`${root}/${encodeURIComponent(id)}`, payload)
}
