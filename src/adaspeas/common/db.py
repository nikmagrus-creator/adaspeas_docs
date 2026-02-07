from __future__ import annotations

import aiosqlite

# NOTE: Use incremental schema versions. Do NOT edit older schema blocks in-place.
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


# v2: cache Telegram file identifiers to avoid re-downloading and re-uploading files.
MIGRATION_V2 = """
ALTER TABLE catalog_items ADD COLUMN tg_file_id TEXT;
ALTER TABLE catalog_items ADD COLUMN tg_file_unique_id TEXT;
"""


# v3: support inline navigation with parent pointers (avoid long callback_data).
MIGRATION_V3 = """
ALTER TABLE catalog_items ADD COLUMN parent_path TEXT;
CREATE INDEX IF NOT EXISTS idx_catalog_parent_path ON catalog_items(parent_path);
"""


# v4: job types (download/sync) + simple meta key-value storage.
MIGRATION_V4 = """
ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'download';

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_type_state ON jobs(job_type, state);
"""

TARGET_SCHEMA_VERSION = 4
MIGRATIONS: dict[int, str] = {
    2: MIGRATION_V2,
    3: MIGRATION_V3,
    4: MIGRATION_V4,
}


async def connect(sqlite_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(sqlite_path)
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    return db


async def _get_schema_version(db: aiosqlite.Connection) -> int:
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
    if not await cur.fetchone():
        return 0
    cur = await db.execute("SELECT version FROM schema_version LIMIT 1")
    row = await cur.fetchone()
    if not row:
        return 0
    return int(row[0])


async def ensure_schema(db: aiosqlite.Connection) -> None:
    # Base schema
    await db.executescript(SCHEMA_V1)

    # Initialize schema_version row if missing
    cur = await db.execute("SELECT COUNT(*) FROM schema_version")
    row = await cur.fetchone()
    if row[0] == 0:
        await db.execute("INSERT INTO schema_version(version) VALUES (1)")
        await db.commit()

    current = await _get_schema_version(db)
    # Apply migrations sequentially
    for ver in range(current + 1, TARGET_SCHEMA_VERSION + 1):
        script = MIGRATIONS.get(ver)
        if not script:
            raise RuntimeError(f"Missing migration script for schema version {ver}")
        await db.executescript(script)
        await db.execute("UPDATE schema_version SET version=?", (ver,))
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
    job_type: str = 'download',
) -> int:
    cur = await db.execute(
        """
        INSERT INTO jobs(tg_chat_id, tg_user_id, catalog_item_id, state, request_id, job_type)
        VALUES (?, ?, ?, 'queued', ?, ?)
        """,
        (tg_chat_id, tg_user_id, catalog_item_id, request_id, job_type),
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
        SELECT id, tg_chat_id, tg_user_id, catalog_item_id, state, attempt, last_error, job_type
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
        "job_type": row[7] or 'download',
    }


async def fetch_catalog_item(db: aiosqlite.Connection, item_id: int) -> dict:
    cur = await db.execute(
        """
        SELECT id, path, kind, title, yandex_id, size_bytes, tg_file_id, tg_file_unique_id, parent_path
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
        "size_bytes": row[5],
        "tg_file_id": row[6],
        "tg_file_unique_id": row[7],
        "parent_path": row[8],
    }


async def set_catalog_item_tg_file(
    db: aiosqlite.Connection,
    item_id: int,
    tg_file_id: str | None,
    tg_file_unique_id: str | None = None,
) -> None:
    await db.execute(
        """
        UPDATE catalog_items
        SET tg_file_id=?, tg_file_unique_id=?, updated_at=datetime('now')
        WHERE id=?
        """,
        (tg_file_id, tg_file_unique_id, item_id),
    )
    await db.commit()


async def upsert_catalog_item(
    db: aiosqlite.Connection,
    path: str,
    kind: str,
    title: str,
    yandex_id: str | None = None,
    size_bytes: int | None = None,
    parent_path: str | None = None,
) -> int:
    """Insert/update catalog item by unique path. Returns item id."""
    await db.execute(
        """
        INSERT INTO catalog_items(path, kind, title, yandex_id, size_bytes, parent_path, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET
          kind=excluded.kind,
          title=excluded.title,
          yandex_id=excluded.yandex_id,
          size_bytes=excluded.size_bytes,
          parent_path=excluded.parent_path,
          updated_at=datetime('now')
        """,
        (path, kind, title, yandex_id, size_bytes, parent_path),
    )
    await db.commit()
    cur = await db.execute("SELECT id FROM catalog_items WHERE path=?", (path,))
    row = await cur.fetchone()
    return int(row[0])


async def fetch_catalog_item_by_path(db: aiosqlite.Connection, path: str) -> dict | None:
    cur = await db.execute(
        """
        SELECT id, path, kind, title, yandex_id, size_bytes, tg_file_id, tg_file_unique_id, parent_path
        FROM catalog_items WHERE path=?
        """,
        (path,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "path": row[1],
        "kind": row[2],
        "title": row[3],
        "yandex_id": row[4],
        "size_bytes": row[5],
        "tg_file_id": row[6],
        "tg_file_unique_id": row[7],
        "parent_path": row[8],
    }


async def fetch_children(
    db: aiosqlite.Connection,
    parent_path: str | None,
    *,
    limit: int = 60,
) -> list[dict]:
    """Fetch immediate children for a folder path."""
    cur = await db.execute(
        """
        SELECT id, kind, title, size_bytes
        FROM catalog_items
        WHERE parent_path IS ?
        ORDER BY kind DESC, title ASC
        LIMIT ?
        """,
        (parent_path, int(limit)),
    )
    rows = await cur.fetchall()
    return [
        {"id": int(r[0]), "kind": r[1], "title": r[2], "size_bytes": r[3]}
        for r in rows
    ]


async def get_meta(db: aiosqlite.Connection, key: str) -> str | None:
    cur = await db.execute('SELECT value FROM meta WHERE key=?', (key,))
    row = await cur.fetchone()
    return str(row[0]) if row else None


async def set_meta(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        'INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (key, value),
    )
    await db.commit()
