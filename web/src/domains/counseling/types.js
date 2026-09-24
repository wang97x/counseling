/** 心理辅导工作台可见领域类型。 */

export const COUNSELING_TABS = ['overview', 'timeline', 'goals', 'assessments', 'crisis']
export const COUNSELING_UPLOAD_EXTENSIONS = ['txt', 'docx', 'pdf']
export const COUNSELING_UPLOAD_MAX_BYTES = 5 * 1024 * 1024

/** @typedef {'normal'|'watch'|'high'|'unknown'} RiskLevel */
/** @typedef {'active'|'paused'|'closed'} StudentStatus */

/**
 * @typedef {Object} StudentSummary
 * @property {string} id
 * @property {string} code
 * @property {string} name
 * @property {string} chiefConcern
 * @property {RiskLevel} riskLevel
 * @property {StudentStatus} status
 * @property {number|null} sessionCount
 * @property {string|null|undefined} nextAppointment
 * @property {string} recentActivity
 * @property {string} counselor
 * @property {number|string|undefined} counselorId
 */

/** @typedef {{id:string,occurredAt:string,title:string,summary:string,source:string,conversationId?:string}} TimelineNode */
/** @typedef {{title:string,content:string}} RecordSummarySection */
/** @typedef {{schemaVersion:1,sections:RecordSummarySection[]}} RecordSummary */

/**
 * @typedef {Object} RecordDraft
 * @property {string} id
 * @property {string} studentId
 * @property {string} status
 * @property {number} version
 * @property {{fileName:string,fileType:string,fileSize:number}} source
 * @property {string} parsedText
 * @property {RecordSummary} summary
 */

/**
 * @typedef {Object} StudentWorkspace
 * @property {StudentSummary} student
 * @property {string} background
 * @property {TimelineNode[]} timeline
 */

export {}
