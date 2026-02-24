import db from '../db/index.js';

/**
 * Notes module — free-form knowledge notes with tagging.
 */

export const NoteContentType = Object.freeze({
  MARKDOWN: 'markdown',
  PLAIN:    'plain',
  CODE:     'code',
  JSON:     'json',
});

/**
 * Create a note.
 */
export async function createNote({ title, body = '', projectId = null, contentType = NoteContentType.MARKDOWN, tags = [] }) {
  const now = new Date().toISOString();
  return db.notes.add({
    title,
    body,
    projectId,
    contentType,
    wordCount: countWords(body),
    tags,
    createdAt: now,
    updatedAt: now,
  });
}

/** Update note body and recount words. */
export async function updateNote(id, { title, body, tags }) {
  const patch = { updatedAt: new Date().toISOString() };
  if (title !== undefined) patch.title = title;
  if (body  !== undefined) { patch.body = body; patch.wordCount = countWords(body); }
  if (tags  !== undefined) patch.tags = tags;
  return db.notes.update(id, patch);
}

/** Full-text-ish search across note titles and bodies (client-side). */
export async function searchNotes(query, { projectId, limit = 50 } = {}) {
  const lower = query.toLowerCase();
  let collection = db.notes.filter(n =>
    n.title?.toLowerCase().includes(lower) ||
    n.body?.toLowerCase().includes(lower)
  );
  if (projectId) {
    collection = db.notes
      .where('projectId').equals(projectId)
      .and(n => n.title?.toLowerCase().includes(lower) || n.body?.toLowerCase().includes(lower));
  }
  return collection.limit(limit).toArray();
}

function countWords(text) {
  return (text ?? '').trim().split(/\s+/).filter(Boolean).length;
}
