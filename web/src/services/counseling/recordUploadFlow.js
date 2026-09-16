/**
 * 上传谈话记录并按适配器能力推进流程。
 * 真实接口当前只完成附件入会话，不能把后续未接入能力呈现为上传失败。
 */
export async function processCounselingRecordUpload(service, studentId, file, options = {}) {
  const uploadResult = await service.uploadRecord(studentId, file, options)
  if (uploadResult.status !== 'ok') return uploadResult

  if (service.mode === 'api') {
    return {
      status: 'ok',
      kind: 'attachment_only',
      uploaded: uploadResult.data,
      message: '附件已加入会话；AI 摘要与归档能力尚未接入。',
    }
  }

  const summaryResult = await service.generateSummary(studentId, uploadResult.data.id)
  if (summaryResult.status !== 'ok') return summaryResult
  return {
    status: 'ok',
    kind: 'summary_draft',
    uploaded: uploadResult.data,
    draft: summaryResult.data,
  }
}
