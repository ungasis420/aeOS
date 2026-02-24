import db from '../db/index.js';

/**
 * Tasks module — task queue with priorities, statuses, and project grouping.
 */

export const TaskStatus = Object.freeze({
  PENDING:    'pending',
  ACTIVE:     'active',
  BLOCKED:    'blocked',
  DONE:       'done',
  CANCELLED:  'cancelled',
});

export const TaskPriority = Object.freeze({
  LOW:    'low',
  NORMAL: 'normal',
  HIGH:   'high',
  URGENT: 'urgent',
});

/**
 * Create a task.
 */
export async function createTask({
  title,
  description = '',
  projectId = null,
  assignedAgentId = null,
  priority = TaskPriority.NORMAL,
  dueAt = null,
  tags = [],
}) {
  const now = new Date().toISOString();
  return db.tasks.add({
    title,
    description,
    projectId,
    assignedAgentId,
    status: TaskStatus.PENDING,
    priority,
    dueAt,
    tags,
    createdAt: now,
    updatedAt: now,
  });
}

/** Get the next pending task (highest priority, then oldest). */
export async function dequeueTask({ projectId, agentId } = {}) {
  const priorityOrder = [TaskPriority.URGENT, TaskPriority.HIGH, TaskPriority.NORMAL, TaskPriority.LOW];

  for (const priority of priorityOrder) {
    let query = db.tasks.where('[status+priority]').equals([TaskStatus.PENDING, priority]);
    if (projectId) {
      const results = await db.tasks
        .where('[projectId+status]').equals([projectId, TaskStatus.PENDING])
        .and(t => t.priority === priority)
        .first();
      if (results) return results;
    } else {
      const task = await query.first();
      if (task) return task;
    }
  }
  return null;
}

/** Transition a task status. */
export async function updateTaskStatus(id, status) {
  return db.tasks.update(id, { status, updatedAt: new Date().toISOString() });
}

/** List tasks for a project with optional status filter. */
export async function listTasks({ projectId, status, priority, limit = 100 } = {}) {
  let records;

  if (projectId && status) {
    records = await db.tasks.where('[projectId+status]').equals([projectId, status]).toArray();
  } else if (status && priority) {
    records = await db.tasks.where('[status+priority]').equals([status, priority]).toArray();
  } else if (status) {
    records = await db.tasks.where('status').equals(status).toArray();
  } else if (projectId) {
    records = await db.tasks.where('projectId').equals(projectId).toArray();
  } else {
    records = await db.tasks.orderBy('createdAt').reverse().toArray();
  }

  return records.slice(0, limit);
}
