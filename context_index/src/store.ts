import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

export function openContextIndexDatabase(databasePath: string): DatabaseSync {
  mkdirSync(dirname(databasePath), { recursive: true });
  const db = new DatabaseSync(databasePath);
  db.exec("PRAGMA journal_mode = WAL");
  db.exec("PRAGMA busy_timeout = 5000");
  db.exec("PRAGMA foreign_keys = ON");
  ensureContextIndexSchema(db);
  return db;
}

export function ensureContextIndexSchema(db: DatabaseSync): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS contexts (
      id TEXT PRIMARY KEY,
      content TEXT NOT NULL,
      summary TEXT NOT NULL,
      context_type TEXT NOT NULL,
      project_id TEXT NOT NULL,
      task_id TEXT,
      keywords_json TEXT NOT NULL,
      entities_json TEXT NOT NULL,
      importance REAL NOT NULL,
      confidence REAL NOT NULL,
      status TEXT NOT NULL,
      source TEXT NOT NULL,
      source_ref TEXT,
      content_hash TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      last_accessed_at INTEGER,
      valid_from INTEGER,
      valid_until INTEGER,
      superseded_by TEXT,
      metadata_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS contexts_scope_idx
      ON contexts(project_id, task_id, status, created_at DESC);
    CREATE INDEX IF NOT EXISTS contexts_hash_idx
      ON contexts(project_id, task_id, content_hash);
    CREATE TABLE IF NOT EXISTS context_relations (
      from_context_id TEXT NOT NULL REFERENCES contexts(id),
      to_context_id TEXT NOT NULL REFERENCES contexts(id),
      relation_type TEXT NOT NULL CHECK (relation_type IN ('supersedes', 'related_to', 'derived_from', 'belongs_to', 'conflicts_with')),
      created_at INTEGER NOT NULL,
      PRIMARY KEY (from_context_id, to_context_id, relation_type)
    );
    CREATE TABLE IF NOT EXISTS context_access_log (
      id TEXT PRIMARY KEY,
      context_id TEXT NOT NULL REFERENCES contexts(id),
      project_id TEXT NOT NULL,
      task_id TEXT,
      stage TEXT NOT NULL,
      score REAL NOT NULL,
      token_count INTEGER NOT NULL,
      accessed_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS context_audit_events (
      id TEXT PRIMARY KEY,
      event_type TEXT NOT NULL,
      context_id TEXT,
      project_id TEXT,
      task_id TEXT,
      session_id TEXT,
      reason TEXT,
      score REAL,
      token_count INTEGER,
      content_hash TEXT,
      timestamp INTEGER NOT NULL,
      metadata_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS context_audit_events_time_idx
      ON context_audit_events(timestamp DESC);
    CREATE VIRTUAL TABLE IF NOT EXISTS contexts_fts USING fts5(
      context_id UNINDEXED,
      content,
      summary,
      keywords
    );
  `);
}
