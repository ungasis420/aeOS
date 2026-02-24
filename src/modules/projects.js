import db from '../db/index.js';

/**
 * Projects module — containers grouping tasks, notes, and memories.
 */

export const ProjectStatus = Object.freeze({
  ACTIVE:    'active',
  PAUSED:    'paused',
  COMPLETED: 'completed',
  ARCHIVED:  'archived',
});

export async function createProject({ name, slug, description = '', ownerId = null, tags = [] }) {
  const now = new Date().toISOString();
  return db.projects.add({
    name,
    slug,
    description,
    status: ProjectStatus.ACTIVE,
    ownerId,
    progress: 0,
    tags,
    startedAt: now,
    archivedAt: null,
    createdAt: now,
    updatedAt: now,
  });
}

export async function getProjectStats(id) {
  const [tasks, notes, memories, events, goals] = await Promise.all([
    db.tasks.where('projectId').equals(id).count(),
    db.notes.where('projectId').equals(id).count(),
    db.memories.count(), // full scan fallback — refine if needed
    db.events.where('projectId').equals(id).count(),
    db.goals.where('projectId').equals(id).count(),
  ]);

  const doneTasks = await db.tasks
    .where('[projectId+status]').equals([id, 'done'])
    .count();

  const progress = tasks > 0 ? Math.round((doneTasks / tasks) * 100) : 0;

  return { tasks, notes, events, goals, progress };
}

export async function archiveProject(id) {
  return db.projects.update(id, {
    status: ProjectStatus.ARCHIVED,
    archivedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });
}
