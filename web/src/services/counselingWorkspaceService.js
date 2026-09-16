import { createCounselingApiAdapter } from './counseling/apiAdapter.js'
import { createCounselingDemoAdapter } from './counseling/demoAdapter.js'

/** 判断是否启用心理辅导工作台演示模式。 */
export function resolveCounselingDemoMode(value = import.meta.env?.VITE_COUNSELING_DEMO) {
  return String(value ?? '').trim().toLowerCase() === 'true'
}

/** 创建统一的心理辅导工作台服务。 */
export function createCounselingWorkspaceService({
  demo = resolveCounselingDemoMode(),
  storage,
} = {}) {
  return demo
    ? createCounselingDemoAdapter({ storage })
    : createCounselingApiAdapter()
}

export const counselingWorkspaceService = createCounselingWorkspaceService()
export { createCounselingApiAdapter, createCounselingDemoAdapter }
