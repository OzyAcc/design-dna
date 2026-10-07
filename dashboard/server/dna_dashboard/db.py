"""SQLite persistence for the single-workspace dashboard.

Canonical engine files (scene, passport, evidence, baselines, bundles) stay on disk and are referenced from these
records; the database holds application state: assets, templates and their immutable versions, products, batch
drafts, jobs with events, runs and outputs. Every schema change is a numbered migration below.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
CREATE TABLE assets (
  id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  role TEXT NOT NULL,                 -- inspiration | product | font | generated | bundle
  original_name TEXT,
  mime TEXT,
  ext TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  width INTEGER, height INTEGER,
  source_kind TEXT NOT NULL,          -- upload | paste | link | page_image | generated | import
  source_url TEXT, page_url TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  provenance TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX assets_sha ON assets(sha256);

CREATE TABLE collections (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE templates (
  id TEXT PRIMARY KEY,
  engine_id TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'original',          -- original | copy
  parent_template_id TEXT REFERENCES templates(id),
  parent_version_id TEXT,
  current_version_id TEXT,
  collection_id TEXT REFERENCES collections(id),
  tags TEXT NOT NULL DEFAULT '[]',
  passport TEXT NOT NULL DEFAULT '{}',             -- searchable passport fields with provenance labels
  source_asset_id TEXT REFERENCES assets(id),
  design_variant TEXT,                              -- engine variant holding copy edits (copies only)
  draft TEXT NOT NULL DEFAULT '{}',                 -- wizard step, proposals, element review, staged rebuild
  draft_revision INTEGER NOT NULL DEFAULT 0,        -- optimistic concurrency for draft saves
  readiness TEXT NOT NULL DEFAULT 'scan_in_progress',
  medium TEXT, aspect_ratio TEXT, width INTEGER, height INTEGER,
  search_text TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE template_versions (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES templates(id),
  number INTEGER NOT NULL,
  bundle_path TEXT NOT NULL,
  bundle_sha256 TEXT NOT NULL,
  engine_id TEXT NOT NULL,
  scene_sha256 TEXT,
  design_variant TEXT,
  design_head INTEGER,
  readiness TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '{}',               -- canvas, slots, baseline, checks, eligibility
  created_from TEXT NOT NULL,                       -- accepted_rebuild | saved_draft | edit | copy | import | restore | migration
  parent_version_id TEXT,
  acceptance TEXT,                                  -- user acceptance record (who/when/level/note)
  thumb_path TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(template_id, number)
);

CREATE TABLE products (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  primary_asset_id TEXT REFERENCES assets(id),
  detail_asset_ids TEXT NOT NULL DEFAULT '[]',
  description TEXT NOT NULL DEFAULT '',
  facts TEXT NOT NULL DEFAULT '[]',
  instructions TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE batches (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',             -- draft | submitted
  revision INTEGER NOT NULL DEFAULT 0,
  template_versions TEXT NOT NULL DEFAULT '[]',     -- [{template_id, version_id}] in selection order
  product_ids TEXT NOT NULL DEFAULT '[]',
  defaults TEXT NOT NULL DEFAULT '{}',              -- batch defaults: copy per slot role, instructions, mode, language
  product_overrides TEXT NOT NULL DEFAULT '{}',     -- {product_id: {copy: {...}, instructions}}
  run_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE batch_pairs (
  id TEXT PRIMARY KEY,                              -- stable: derived from batch, product, template, variant index
  batch_id TEXT NOT NULL REFERENCES batches(id),
  product_id TEXT NOT NULL,
  template_id TEXT NOT NULL,
  template_version_id TEXT NOT NULL,
  variant_index INTEGER NOT NULL DEFAULT 0,
  included INTEGER NOT NULL DEFAULT 1,
  attached INTEGER NOT NULL DEFAULT 1,              -- 0 when its product/template left the selection (content kept)
  mode TEXT,                                         -- null = batch default
  language TEXT,
  pair_overrides TEXT NOT NULL DEFAULT '{}',        -- bulk-applied values {slot_id: {value}}
  manual TEXT NOT NULL DEFAULT '{}',                -- typed in the output editor {slot_id: {value, source, approved}}
  instructions TEXT,
  ai_drafts TEXT NOT NULL DEFAULT '{}',             -- unapplied proposals {slot_id: {value, request_id, at}}
  preview TEXT NOT NULL DEFAULT '{}',               -- last fit preview result
  version_check TEXT,                               -- set when the selected version's slots differ from authored ones
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(batch_id, product_id, template_id, variant_index)
);

CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL REFERENCES batches(id),
  name TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  snapshot TEXT NOT NULL,                           -- frozen inputs at submission
  created_at TEXT NOT NULL
);

CREATE TABLE outputs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  pair_id TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  parent_output_id TEXT,
  product_id TEXT NOT NULL,
  template_id TEXT NOT NULL,
  template_version_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  language TEXT NOT NULL,
  inputs TEXT NOT NULL,                             -- frozen resolved copy, instructions, product snapshot
  status TEXT NOT NULL DEFAULT 'queued',
  review_state TEXT NOT NULL DEFAULT 'unreviewed',  -- unreviewed | approved | rejected
  job_id TEXT,
  files TEXT NOT NULL DEFAULT '[]',
  checks TEXT NOT NULL DEFAULT '{}',
  limitations TEXT NOT NULL DEFAULT '[]',
  provenance TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX outputs_run ON outputs(run_id);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',            -- queued | running | needs_review | completed | failed | cancelled
  stage TEXT,
  lock_key TEXT,                                    -- jobs sharing a lock run one at a time (template workspaces)
  priority INTEGER NOT NULL DEFAULT 5,
  input TEXT NOT NULL,
  result TEXT,
  error TEXT,
  idempotency_key TEXT UNIQUE,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 1,
  lease_owner TEXT,
  lease_expires REAL,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  template_id TEXT, run_id TEXT, output_id TEXT, batch_id TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX jobs_status ON jobs(status, priority, created_at);

CREATE TABLE job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  at TEXT NOT NULL,
  stage TEXT,
  level TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  data TEXT
);
CREATE INDEX job_events_job ON job_events(job_id, id);

CREATE TABLE provider_requests (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  provider TEXT NOT NULL,
  operation TEXT NOT NULL,
  model TEXT,
  status TEXT NOT NULL,                             -- sending | received | failed | unknown
  request_id TEXT,
  detail TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE migrations (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  version_id TEXT,
  preview_id TEXT,
  status TEXT NOT NULL,                             -- previewed | confirmed | rejected
  data TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.get().db_path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = 0
    for version, sql in MIGRATIONS:
        if version in done:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in [s for s in sql.split(";\n") if s.strip()]:
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, now()))
            conn.execute("COMMIT")
            applied += 1
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return applied


@contextmanager
def tx(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE ... COMMIT: a writer transaction (serialises with the worker's job claims)."""
    for attempt in range(50):
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or attempt == 49:
                raise
            time.sleep(0.1)
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=False, default=str)


def loads(v, default=None):
    if v is None:
        return default
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


JSON_COLUMNS = {"metadata", "provenance", "tags", "passport", "draft", "summary", "acceptance", "detail_asset_ids", "facts",
                "template_versions", "product_ids", "defaults", "product_overrides", "pair_overrides", "manual", "ai_drafts",
                "preview", "version_check", "snapshot", "inputs", "files", "checks", "limitations", "input", "result", "error",
                "data", "detail"}


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    out = dict(r)
    for k, v in out.items():
        if k in JSON_COLUMNS and isinstance(v, str):
            out[k] = loads(v, v)
    return out


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]


def one(conn, sql, params=()) -> dict | None:
    return row(conn.execute(sql, params).fetchone())


def all_(conn, sql, params=()) -> list[dict]:
    return rows(conn.execute(sql, params).fetchall())


def insert(conn, table: str, values: dict) -> None:
    cols = list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 [dumps(v) if (k in JSON_COLUMNS and v is not None and not isinstance(v, str)) else v for k, v in values.items()])


def update(conn, table: str, key: str, values: dict) -> None:
    cols = list(values)
    conn.execute(f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                 [dumps(v) if (k in JSON_COLUMNS and v is not None and not isinstance(v, str)) else v for k, v in values.items()] + [key])
