import db from '../db/index.js';

/**
 * Agents module — CRUD and lifecycle helpers for agent configurations.
 */

export const AgentStatus = Object.freeze({
  IDLE:    'idle',
  ACTIVE:  'active',
  PAUSED:  'paused',
  ERROR:   'error',
  RETIRED: 'retired',
});

export const AgentType = Object.freeze({
  ASSISTANT:  'assistant',
  ANALYST:    'analyst',
  SCHEDULER:  'scheduler',
  MONITOR:    'monitor',
  RESEARCHER: 'researcher',
});

/**
 * Create a new agent record.
 * @param {{ name: string, slug: string, type: string, capabilities?: string[] }} params
 */
export async function createAgent({ name, slug, type = AgentType.ASSISTANT, capabilities = [] }) {
  const now = new Date().toISOString();
  return db.agents.add({
    name,
    slug,
    type,
    status: AgentStatus.IDLE,
    capabilities,
    config: {},
    createdAt: now,
    updatedAt: now,
  });
}

/** List all agents, optionally filtered by status. */
export async function listAgents({ status } = {}) {
  let query = db.agents.orderBy('name');
  if (status) {
    query = db.agents.where('status').equals(status);
  }
  return query.toArray();
}

/** Get a single agent by id or slug. */
export async function getAgent(idOrSlug) {
  if (typeof idOrSlug === 'number') return db.agents.get(idOrSlug);
  return db.agents.where('slug').equals(idOrSlug).first();
}

/** Update an agent's status. */
export async function setAgentStatus(id, status) {
  return db.agents.update(id, { status, updatedAt: new Date().toISOString() });
}

/** Delete an agent and all its dependent sessions/memories. */
export async function deleteAgent(id) {
  await db.transaction('rw', [db.agents, db.sessions, db.memories], async () => {
    await db.sessions.where('agentId').equals(id).delete();
    await db.memories.where('agentId').equals(id).delete();
    await db.agents.delete(id);
  });
}
