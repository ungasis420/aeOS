import db from '../db/index.js';

/**
 * Insights module — generated analysis records with confidence scoring.
 */

export const InsightCategory = Object.freeze({
  PATTERN:     'pattern',
  ANOMALY:     'anomaly',
  TREND:       'trend',
  SUMMARY:     'summary',
  SUGGESTION:  'suggestion',
  CORRELATION: 'correlation',
});

/**
 * Record a new insight.
 */
export async function recordInsight({
  agentId = null,
  sourceType,
  sourceId,
  category = InsightCategory.SUMMARY,
  title,
  body,
  confidence = 0.8,
  tags = [],
}) {
  const now = new Date().toISOString();
  return db.insights.add({
    agentId,
    sourceType,
    sourceId,
    category,
    title,
    body,
    confidence: Math.max(0, Math.min(1, confidence)),
    tags,
    generatedAt: now,
    createdAt: now,
    updatedAt: now,
  });
}

/** Retrieve insights by category, sorted by confidence descending. */
export async function getInsights({ category, agentId, minConfidence = 0, limit = 50 } = {}) {
  let records;

  if (agentId) {
    records = await db.insights.where('agentId').equals(agentId).toArray();
  } else if (category) {
    records = await db.insights.where('category').equals(category).toArray();
  } else {
    records = await db.insights.orderBy('generatedAt').reverse().toArray();
  }

  return records
    .filter(i => i.confidence >= minConfidence)
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, limit);
}

/**
 * Compute a lightweight summary insight from recent task completions.
 * This is a pure client-side heuristic — no LLM required.
 */
export async function generateTaskInsight(agentId) {
  const tasks = await db.tasks
    .where('status').equals('done')
    .and(t => !agentId || t.assignedAgentId === agentId)
    .limit(100)
    .toArray();

  if (tasks.length < 3) return null;

  const byPriority = tasks.reduce((acc, t) => {
    acc[t.priority] = (acc[t.priority] ?? 0) + 1;
    return acc;
  }, {});

  const topPriority = Object.entries(byPriority).sort((a, b) => b[1] - a[1])[0];

  return recordInsight({
    agentId,
    sourceType: 'tasks',
    sourceId: null,
    category: InsightCategory.SUMMARY,
    title: `${tasks.length} tasks completed`,
    body: `Most frequent priority: ${topPriority?.[0] ?? 'unknown'} (${topPriority?.[1] ?? 0} tasks).`,
    confidence: 0.9,
    tags: ['auto-generated', 'tasks'],
  });
}
