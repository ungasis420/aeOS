import Dexie from 'dexie';
import { SCHEMAS, SCHEMA_VERSION } from './schemas.js';

/**
 * aeOS database — a Dexie wrapper over IndexedDB.
 * All 13 tables are declared on `db` and accessible as `db.<tableName>`.
 */
class AeOSDatabase extends Dexie {
  constructor() {
    super('aeos_intelligence');

    this.version(SCHEMA_VERSION).stores(SCHEMAS);

    // Hook: auto-set createdAt / updatedAt on write
    this.tables.forEach((table) => {
      table.hook('creating', (_primKey, obj) => {
        const now = new Date().toISOString();
        if ('createdAt' in table.schema.indexes.reduce((acc, i) => ({ ...acc, [i.name]: true }), {}) ||
            table.schema.primKey) {
          if (obj.createdAt === undefined) obj.createdAt = now;
          if (obj.updatedAt === undefined) obj.updatedAt = now;
        }
      });

      table.hook('updating', (mods) => {
        if ('updatedAt' in table.schema.indexes.reduce((acc, i) => ({ ...acc, [i.name]: true }), {}) ||
            true) {
          mods.updatedAt = new Date().toISOString();
        }
        return mods;
      });
    });
  }
}

export const db = new AeOSDatabase();

/**
 * Verify the database opens successfully and seed default settings if empty.
 */
export async function initDatabase() {
  await db.open();

  const settingsCount = await db.settings.count();
  if (settingsCount === 0) {
    await db.settings.bulkPut([
      { key: 'app.version', value: '0.1.0', group: 'system', updatedAt: new Date().toISOString() },
      { key: 'app.theme', value: 'dark', group: 'ui', updatedAt: new Date().toISOString() },
      { key: 'app.language', value: 'en', group: 'ui', updatedAt: new Date().toISOString() },
      { key: 'intelligence.maxMemories', value: 10000, group: 'intelligence', updatedAt: new Date().toISOString() },
      { key: 'intelligence.autoInsights', value: true, group: 'intelligence', updatedAt: new Date().toISOString() },
      { key: 'sync.enabled', value: false, group: 'sync', updatedAt: new Date().toISOString() },
    ]);
  }

  return db;
}

export default db;
