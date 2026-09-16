const normalizeText = (value) => String(value || '').trim()

/** 根据当前档案生成可执行、可人工核对的下一步话题。 */
export function buildNextStepTopics(workspace) {
  if (!workspace) return []

  const topics = []
  const todo = workspace.todos?.find((item) => item.status === 'todo')
  const goal = workspace.goals?.find((item) => item.status !== 'done')
  const riskLevel = workspace.student?.riskLevel

  if (todo) {
    const detail = normalizeText(todo.title)
    topics.push({
      id: 'todo',
      title: '推进当前待办',
      description: detail,
      prompt: `请帮我规划如何在下次谈话中推进这项待办：${detail}`,
    })
  }

  if (goal) {
    const detail = normalizeText(goal.homework) || normalizeText(goal.title)
    topics.push({
      id: 'goal',
      title: '跟进目标与作业',
      description: detail,
      prompt: `请围绕当前目标“${normalizeText(goal.title)}”设计一个可执行的跟进话题，重点核对：${detail}`,
    })
  }

  if (riskLevel === 'high' || riskLevel === 'watch') {
    topics.push({
      id: 'risk',
      title: '人工复核风险信息',
      description: '核对信号、保护因素与支持资源',
      prompt: '请列出下次谈话中需要人工核对的风险信号、保护因素和支持资源；不要把建议表述为已完成处置。',
    })
  } else {
    const recent = workspace.timeline?.[0]
    topics.push({
      id: 'change',
      title: '回顾近期变化',
      description: normalizeText(recent?.title) || '比较本阶段前后变化',
      prompt: '请基于时间轴整理下次谈话值得回顾的近期变化，并给出三个开放式问题。',
    })
  }

  if (topics.length < 3) {
    topics.push({
      id: 'prepare',
      title: '准备下一次谈话',
      description: '整理开场、核对点与结束约定',
      prompt: '请基于当前档案准备下一次谈话，整理开场、需要人工核对的重点和结束前的行动约定。',
    })
  }

  if (topics.length < 3) {
    topics.push({
      id: 'focus',
      title: '梳理本次重点',
      description: normalizeText(workspace.student?.chiefConcern) || '从当前档案确定一个优先话题',
      prompt: '请基于当前档案梳理本次谈话最值得优先推进的一个话题，并说明需要人工核对的信息。',
    })
  }

  return topics.slice(0, 3)
}
