import { createCounselingApiAdapter } from './services/apiAdapter.js'

/** 创建只使用真实后端的心理辅导工作台服务。 */
export function createCounselingWorkspaceService() {
  return createCounselingApiAdapter()
}

export const counselingWorkspaceService = createCounselingWorkspaceService()
export { createCounselingApiAdapter }
