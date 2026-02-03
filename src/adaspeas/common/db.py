from __future__ import annotations

import aiosqlite

SCHEMA_V1 = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  tg_user_id INTEGER NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS roles (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id INTEGER NOT NULL,
  role_id INTEGER NOT NULL,
  PRIMARY KEY (user_id, role_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS catalog_items (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK(kind IN ('folder','file')),
  title TEXT NOT NULL,
  yandex_id TEXT,
  size_bytes INTEGER,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  tg_chat_id INTEGER NOT NULL,
  tg_user_id INTEGER NOT NULL,
  catalog_item_id INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','cancelled')),
  attempt INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  request_id TEXT NOT NULL,
  UNIQUE(tg_chat_id, catalog_item_id, request_id),
  FOREIGN KEY (catalog_item_id) REFERENCES catalog_items(id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_catalog_path ON catalog_items(path);
"""


async def connect(sqlite_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(sqlite_path)
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    return db


async def ensure_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(SCHEMA_V1)
    # initialize schema_version
    cur = await db.execute("SELECT COUNT(*) FROM schema_version")
    row = await cur.fetchone()
    if row[0] == 0:
        await db.execute("INSERT INTO schema_version(version) VALUES (1)")
        await db.commit()


async def upsert_user(db: aiosqlite.Connection, tg_user_id: int) -> int:
    await db.execute(
        "INSERT INTO users(tg_user_id) VALUES (?) ON CONFLICT(tg_user_id) DO NOTHING",
        (tg_user_id,),
    )
    await db.commit()
    cur = await db.execute("SELECT id FROM users WHERE tg_user_id=?", (tg_user_id,))
    row = await cur.fetchone()
    return int(row[0])


async def insert_job(
    db: aiosqlite.Connection,
    tg_chat_id: int,
    tg_user_id: int,
    catalog_item_id: int,
    request_id: str,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO jobs(tg_chat_id, tg_user_id, catalog_item_id, state, request_id)
        VALUES (?, ?, ?, 'queued', ?)
        """,
        (tg_chat_id, tg_user_id, catalog_item_id, request_id),
    )
    await db.commit()
    return int(cur.lastrowid)


async def set_job_state(
    db: aiosqlite.Connection,
    job_id: int,
    state: str,
    last_error: str | None = None,
) -> None:
    await db.execute(
        """
        UPDATE jobs
        SET state=?, last_error=?, updated_at=datetime('now')
        WHERE id=?
        """,
        (state, last_error, job_id),
    )
    await db.commit()


async def bump_attempt(db: aiosqlite.Connection, job_id: int, last_error: str) -> int:
    await db.execute(
        """
        UPDATE jobs
        SET attempt = attempt + 1,
            last_error=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (last_error, job_id),
    )
    await db.commit()
    cur = await db.execute("SELECT attempt FROM jobs WHERE id=?", (job_id,))
    row = await cur.fetchone()
    return int(row[0])


async def fetch_job(db: aiosqlite.Connection, job_id: int) -> dict:
    cur = await db.execute(
        """
        SELECT id, tg_chat_id, tg_user_id, catalog_item_id, state, attempt, last_error
        FROM jobs WHERE id=?
        """,
        (job_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise KeyError(f"job {job_id} not found")
    return {
        "id": int(row[0]),
        "tg_chat_id": int(row[1]),
        "tg_user_id": int(row[2]),
        "catalog_item_id": int(row[3]),
        "state": row[4],
        "attempt": int(row[5]),
        "last_error": row[6],
    }


async def fetch_catalog_item(db: aiosqlite.Connection, item_id: int) -> dict:
    cur = await db.execute(
        """
        SELECT id, path, kind, title, yandex_id
        FROM catalog_items WHERE id=?
        """,
        (item_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise KeyError(f"catalog_item {item_id} not found")
    return {
        "id": int(row[0]),
        "path": row[1],
        "kind": row[2],
        "title": row[3],
        "yandex_id": row[4],
    }
