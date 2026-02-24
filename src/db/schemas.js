/**
 * aeOS — IndexedDB Schema Definitions
 *
 * 13 schemas powering the intelligence layer.
 * Dexie.js syntax: '++id' = auto-increment PK, '&field' = unique index,
 * '[a+b]' = compound index, '*tags' = multi-entry index.
 */

export const SCHEMA_VERSION = 1;

/**
 * Schema map passed to Dexie's .stores() method.
 *
 * 1.  agents      — AI/automation agent configurations
 * 2.  sessions    — Runtime session records (agent or user)
 * 3.  memories    — Long-term memory entries with vector-ready embeddings
 * 4.  tasks       — Actionable task queue
 * 5.  notes       — Free-form knowledge notes
 * 6.  thoughts    — Ephemeral stream-of-consciousness captures
 * 7.  connections — Directed relationship graph edges
 * 8.  tags        — Taxonomy nodes shared across collections
 * 9.  projects    — Container grouping tasks, notes, and memories
 * 10. events      — Timestamped timeline events
 * 11. goals       — High-level goal tracking
 * 12. insights    — Computed/generated analysis records
 * 13. settings    — Key-value system configuration store
 */
export const SCHEMAS = {
  // 1. Agents
  agents: '++id, &slug, name, type, status, *capabilities, createdAt, updatedAt',

  // 2. Sessions
  sessions: '++id, agentId, userId, type, status, startedAt, endedAt, [agentId+status]',

  // 3. Memories
  memories:
    '++id, agentId, sessionId, type, importance, *tags, createdAt, updatedAt, [agentId+type], [agentId+importance]',

  // 4. Tasks
  tasks: '++id, projectId, assignedAgentId, title, status, priority, dueAt, *tags, createdAt, updatedAt, [projectId+status], [status+priority]',

  // 5. Notes
  notes: '++id, projectId, title, contentType, *tags, createdAt, updatedAt, [projectId+createdAt]',

  // 6. Thoughts
  thoughts: '++id, agentId, sessionId, content, mood, *tags, capturedAt, [agentId+capturedAt]',

  // 7. Connections
  connections: '++id, sourceId, sourceType, targetId, targetType, relation, weight, *tags, createdAt, [sourceId+sourceType], [targetId+targetType], [sourceId+relation]',

  // 8. Tags
  tags: '++id, &slug, label, color, category, useCount, createdAt',

  // 9. Projects
  projects: '++id, &slug, name, status, ownerId, *tags, startedAt, archivedAt, createdAt, updatedAt',

  // 10. Events
  events: '++id, projectId, agentId, type, title, *tags, occurredAt, createdAt, [type+occurredAt], [projectId+occurredAt]',

  // 11. Goals
  goals: '++id, projectId, title, status, progress, targetDate, *tags, createdAt, updatedAt, [status+targetDate]',

  // 12. Insights
  insights: '++id, sourceType, sourceId, agentId, category, confidence, *tags, generatedAt, [agentId+generatedAt], [category+confidence]',

  // 13. Settings
  settings: '&key, value, group, updatedAt',
};

/**
 * Human-readable metadata for each schema — used in UI and migration docs.
 */
export const SCHEMA_META = {
  agents: {
    label: 'Agents',
    description: 'AI/automation agent configurations and capabilities',
    icon: 'agent',
    color: 'var(--color-accent-blue)',
  },
  sessions: {
    label: 'Sessions',
    description: 'Runtime session records linking agents to activity windows',
    icon: 'session',
    color: 'var(--color-accent-purple)',
  },
  memories: {
    label: 'Memories',
    description: 'Long-term memory entries with importance scoring',
    icon: 'memory',
    color: 'var(--color-accent-cyan)',
  },
  tasks: {
    label: 'Tasks',
    description: 'Actionable task queue with priority and due-date tracking',
    icon: 'task',
    color: 'var(--color-accent-green)',
  },
  notes: {
    label: 'Notes',
    description: 'Free-form knowledge notes with rich content support',
    icon: 'note',
    color: 'var(--color-accent-yellow)',
  },
  thoughts: {
    label: 'Thoughts',
    description: 'Ephemeral stream-of-consciousness captures',
    icon: 'thought',
    color: 'var(--color-accent-orange)',
  },
  connections: {
    label: 'Connections',
    description: 'Directed relationship graph edges between any entities',
    icon: 'connection',
    color: 'var(--color-accent-pink)',
  },
  tags: {
    label: 'Tags',
    description: 'Shared taxonomy nodes used to classify any record',
    icon: 'tag',
    color: 'var(--color-accent-teal)',
  },
  projects: {
    label: 'Projects',
    description: 'Containers grouping tasks, notes, and memories',
    icon: 'project',
    color: 'var(--color-accent-indigo)',
  },
  events: {
    label: 'Events',
    description: 'Timestamped timeline events across the system',
    icon: 'event',
    color: 'var(--color-accent-red)',
  },
  goals: {
    label: 'Goals',
    description: 'High-level goal tracking with progress measurement',
    icon: 'goal',
    color: 'var(--color-accent-lime)',
  },
  insights: {
    label: 'Insights',
    description: 'Computed and generated analysis records with confidence scores',
    icon: 'insight',
    color: 'var(--color-accent-amber)',
  },
  settings: {
    label: 'Settings',
    description: 'Key-value system configuration store',
    icon: 'settings',
    color: 'var(--color-surface-3)',
  },
};
