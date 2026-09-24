import {
  COUNSELING_UPLOAD_EXTENSIONS,
  COUNSELING_UPLOAD_MAX_BYTES,
} from '../types.js'

/** 校验工作台文本记录文件边界；返回 null 表示可继续。 */
export function validateCounselingUpload(file) {
  const extension = String(file?.name || '').split('.').pop().toLowerCase()
  if (!COUNSELING_UPLOAD_EXTENSIONS.includes(extension)) {
    return { status: 'error', code: 'invalid_type', message: '仅支持 TXT、DOCX、PDF 文件' }
  }
  if (!file?.size) return { status: 'error', code: 'empty_file', message: '文件不能为空' }
  if (file.size > COUNSELING_UPLOAD_MAX_BYTES) {
    return { status: 'error', code: 'file_too_large', message: '文件不能超过 5 MB' }
  }
  return null
}
