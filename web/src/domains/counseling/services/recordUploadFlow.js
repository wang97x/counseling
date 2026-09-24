/** 上传谈话记录，并返回可由辅导员审阅的摘要草稿。 */
export async function processCounselingRecordUpload(service, studentId, file, options = {}) {
  if (service.mode === 'api') {
    const uploadResult = await service.createRecordDraft(
      studentId,
      file,
      options.requestId || crypto.randomUUID(),
    )
    if (uploadResult.status !== 'ok') return uploadResult

    const summaryResult = await service.generateSummary(
      studentId,
      uploadResult.data.id,
      uploadResult.data.version,
      crypto.randomUUID(),
    )
    if (summaryResult.status !== 'ok') return summaryResult
    return {
      status: 'ok',
      kind: 'record_draft',
      uploaded: {
        name: summaryResult.data.source.fileName,
        parsedPreview: summaryResult.data.parsedText.slice(0, 160),
      },
      draft: summaryResult.data,
    }
  }

  const uploadResult = await service.uploadRecord(studentId, file, options)
  if (uploadResult.status !== 'ok') return uploadResult

  const summaryResult = await service.generateSummary(studentId, uploadResult.data.id)
  if (summaryResult.status !== 'ok') return summaryResult
  return {
    status: 'ok',
    kind: 'summary_draft',
    uploaded: uploadResult.data,
    draft: summaryResult.data,
  }
}
