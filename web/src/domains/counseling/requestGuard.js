/** 判断异步学生请求是否仍属于当前档案与请求代次。 */
export function isCurrentStudentRequest(requestStudentId, requestVersion, currentStudentId, currentVersion) {
  return String(requestStudentId) === String(currentStudentId) && requestVersion === currentVersion
}

/** 判断弹窗异步操作是否仍属于打开的当前学生上下文。 */
export function isCurrentCounselingOperation(
  operations,
  operation,
  requestStudentId,
  currentStudentId,
  open,
) {
  return Boolean(open) && String(requestStudentId) === String(currentStudentId) && operations.isCurrent(operation)
}

/** 创建可失效的异步操作代次，避免旧 finally 干扰新操作。 */
export function createLatestOperation() {
  let revision = 0
  return {
    begin: () => ++revision,
    invalidate: () => ++revision,
    isCurrent: (operation) => operation === revision,
  }
}
