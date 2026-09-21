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

/** @typedef {{id:string,title:string,status:'todo'|'done',dueAt?:string}} WorkspaceTodo */
/** @typedef {{id:string,occurredAt:string,title:string,summary:string,moodBefore?:number,moodAfter?:number,source:'manual'|'upload'|'assistant',conversationId?:string}} SessionRecord */
/** @typedef {{id:string,title:string,progress:number,status:'active'|'done',homework?:string}} Goal */
/** @typedef {{name:string,points:Array<{date:string,value:number}>,interpretation:string}} AssessmentSeries */
/** @typedef {{id:string,occurredAt:string,level:RiskLevel,signal:string,response:string,status:'monitoring'|'closed'}} CrisisEvent */
/** @typedef {{id:string,name:string,size:number,type:string,status:'parsed'|'failed',parsedPreview:string,createdAt:string}} UploadedRecord */

/**
 * @typedef {Object} SummaryDraft
 * @property {string} id
 * @property {string} studentId
 * @property {string} uploadId
 * @property {string} emotion
 * @property {string} coreIssue
 * @property {string} pattern
 * @property {string} riskAssessment
 * @property {RiskLevel} riskLevel
 * @property {string} homework
 * @property {string} nextPlan
 */

/** @typedef {{section:'timeline'|'goals'|'assessments'|'crisis'|'todos',action:'add'|'update',description:string} ArchiveImpact */
/** @typedef {{draftId:string,impacts:ArchiveImpact[],requiresRiskAcknowledgement:boolean}} ArchivePreview */

/**
 * @typedef {Object} StudentWorkspace
 * @property {StudentSummary} student
 * @property {string} background
 * @property {WorkspaceTodo[]} todos
 * @property {SessionRecord[]} timeline
 * @property {Goal[]} goals
 * @property {AssessmentSeries[]} assessments
 * @property {CrisisEvent[]} crises
 * @property {UploadedRecord[]} uploads
 */

export {}
