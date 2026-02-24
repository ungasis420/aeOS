import db from '../db/index.js';

/**
 * Memories module — store, retrieve, and score long-term memory entries.
 */

export const MemoryType = Object.freeze({
  FACT:        'fact',
  OBSERVATION: 'observation',
  PREFERENCE:  'preference',
  PROCEDURE:   'procedure',
  REFLECTION:  'reflection',
  CONTEXT:     'context',
});

/**
 * Store a new memory.
 * @param {{ agentId?: number, sessionId?: number, type: string, content: string, importance?: number, tags?: string[] }} params
 */
export async function storeMemory({ agentId, sessionId, type = MemoryType.FACT, content, importance = 5, tags = [] }) {
  const now = new Date().toISOString();
  return db.memories.add({
    agentId,
    sessionId,
    type,
    content,
    importance: Math.max(1, Math.min(10, importance)),
    embedding: null, // placeholder for future vector support
    tags,
    createdAt: now,
    updatedAt: now,
  });
}

/**
 * Retrieve memories by agent, optionally sorted by importance.
 */
export async function recallMemories({ agentId, type, minImportance = 1, limit = 100 } = {}) {
  let collection;

  if (agentId && type) {
    collection = db.memories.where('[agentId+type]').equals([agentId, type]);
  } else if (agentId) {
    collection = db.memories.where('agentId').equals(agentId);
  } else {
    collection = db.memories.orderBy('importance').reverse();
  }

  const records = await collection.toArray();
  return records
    .filter(m => m.importance >= minImportance)
    .sort((a, b) => b.importance - a.importance)
    .slice(0, limit);
}

/** Bump the importance score of a memory (reinforcement). */
export async function reinforceMemory(id, delta = 1) {
  const memory = await db.memories.get(id);
  if (!memory) return;
  const importance = Math.min(10, memory.importance + delta);
  return db.memories.update(id, { importance, updatedAt: new Date().toISOString() });
}

/** Delete memories older than `days` with importance below threshold. */
export async function pruneMemories({ days = 90, maxImportance = 3 } = {}) {
  const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();
  return db.memories
    .where('createdAt').below(cutoff)
    .and(m => m.importance <= maxImportance)
    .delete();
}
