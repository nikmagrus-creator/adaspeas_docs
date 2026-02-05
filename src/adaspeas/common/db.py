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
  parent_id INTEGER,
  path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK(kind IN ('folder','file')),
  title TEXT NOT NULL,
  yandex_id TEXT,
  size_bytes INTEGER,
  yandex_modified TEXT,
  yandex_md5 TEXT,
  tg_file_id TEXT,
  tg_file_unique_id TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (parent_id) REFERENCES catalog_items(id) ON DELETE SET NULL
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
CREATE INDEX IF NOT EXISTS idx_catalog_parent ON catalog_items(parent_id);
"""


async def connect(sqlite_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(sqlite_path)
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    return db


async def ensure_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(SCHEMA_V1)

    # schema_version is a single-row table (version as primary key)
    cur = await db.execute("SELECT version FROM schema_version LIMIT 1")
    row = await cur.fetchone()
    if row is None:
        await db.execute("INSERT INTO schema_version(version) VALUES (1)")
        await db.commit()
        version = 1
    else:
        version = int(row[0])

    # v2: file_id cache + yandex fingerprints
    if version < 2:
        await _ensure_catalog_columns_v2(db)
        await db.execute("UPDATE schema_version SET version=2")
        await db.commit()

    # v3: parent_id for inline tree navigation
    if version < 3:
        await _ensure_catalog_columns_v3(db)
        await db.execute("UPDATE schema_version SET version=3")
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
        SELECT id, parent_id, path, kind, title, yandex_id, yandex_md5, tg_file_id, tg_file_unique_id
        FROM catalog_items WHERE id=?
        """,
        (item_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise KeyError(f"catalog_item {item_id} not found")
    return {
        "id": int(row[0]),
        "parent_id": (int(row[1]) if row[1] is not None else None),
        "path": row[2],
        "kind": row[3],
        "title": row[4],
        "yandex_id": row[5],
        "yandex_md5": row[6],
        "tg_file_id": row[7],
        "tg_file_unique_id": row[8],
    }


async def upsert_catalog_item(
    db: aiosqlite.Connection,
    path: str,
    kind: str,
    title: str,
    parent_id: int | None = None,
    yandex_id: str | None = None,
    size_bytes: int | None = None,
    yandex_modified: str | None = None,
    yandex_md5: str | None = None,
) -> int:
    """Insert/update catalog item by unique path. Returns item id."""
    await db.execute(
        """
        INSERT INTO catalog_items(
          path, parent_id, kind, title, yandex_id, size_bytes,
          yandex_modified, yandex_md5,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET
          parent_id=excluded.parent_id,
          kind=excluded.kind,
          title=excluded.title,
          yandex_id=excluded.yandex_id,
          size_bytes=excluded.size_bytes,
          yandex_modified=excluded.yandex_modified,
          yandex_md5=excluded.yandex_md5,
          tg_file_id=CASE
            WHEN excluded.yandex_md5 IS NOT NULL
             AND catalog_items.yandex_md5 IS NOT NULL
             AND excluded.yandex_md5 != catalog_items.yandex_md5
            THEN NULL
            ELSE catalog_items.tg_file_id
          END,
          tg_file_unique_id=CASE
            WHEN excluded.yandex_md5 IS NOT NULL
             AND catalog_items.yandex_md5 IS NOT NULL
             AND excluded.yandex_md5 != catalog_items.yandex_md5
            THEN NULL
            ELSE catalog_items.tg_file_unique_id
          END,
          updated_at=datetime('now')
        """,
        (path, parent_id, kind, title, yandex_id, size_bytes, yandex_modified, yandex_md5),
    )
    await db.commit()
    cur = await db.execute("SELECT id FROM catalog_items WHERE path=?", (path,))
    row = await cur.fetchone()
    return int(row[0])


async def set_catalog_item_tg_file(db: aiosqlite.Connection, item_id: int, tg_file_id: str, tg_file_unique_id: str | None) -> None:
    await db.execute(
        """
        UPDATE catalog_items
        SET tg_file_id=?, tg_file_unique_id=?, updated_at=datetime('now')
        WHERE id=?
        """,
        (tg_file_id, tg_file_unique_id, item_id),
    )
    await db.commit()


async def clear_catalog_item_tg_file(db: aiosqlite.Connection, item_id: int) -> None:
    await db.execute(
        """
        UPDATE catalog_items
        SET tg_file_id=NULL, tg_file_unique_id=NULL, updated_at=datetime('now')
        WHERE id=?
        """,
        (item_id,),
    )
    await db.commit()


async def _table_has_column(db: aiosqlite.Connection, table: str, column: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return any(r[1] == column for r in rows)


async def _ensure_catalog_columns_v2(db: aiosqlite.Connection) -> None:
    # Keep migrations idempotent for local dev.
    if not await _table_has_column(db, "catalog_items", "yandex_modified"):
        await db.execute("ALTER TABLE catalog_items ADD COLUMN yandex_modified TEXT")
    if not await _table_has_column(db, "catalog_items", "yandex_md5"):
        await db.execute("ALTER TABLE catalog_items ADD COLUMN yandex_md5 TEXT")
    if not await _table_has_column(db, "catalog_items", "tg_file_id"):
        await db.execute("ALTER TABLE catalog_items ADD COLUMN tg_file_id TEXT")
    if not await _table_has_column(db, "catalog_items", "tg_file_unique_id"):
        await db.execute("ALTER TABLE catalog_items ADD COLUMN tg_file_unique_id TEXT")


async def _ensure_catalog_columns_v3(db: aiosqlite.Connection) -> None:
    # Keep migrations idempotent for local dev.
    if not await _table_has_column(db, "catalog_items", "parent_id"):
        await db.execute("ALTER TABLE catalog_items ADD COLUMN parent_id INTEGER")
    # Index is safe to (re)create.
    await db.execute("CREATE INDEX IF NOT EXISTS idx_catalog_parent ON catalog_items(parent_id)")


async def ensure_root_catalog_item(db: aiosqlite.Connection, title: str = "Каталог") -> int:
    """Ensure a virtual root folder exists (path='/') and return its id."""
    await db.execute(
        """
        INSERT INTO catalog_items(path, parent_id, kind, title, yandex_id, updated_at)
        VALUES ('/', NULL, 'folder', ?, NULL, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET
          parent_id=NULL,
          kind='folder',
          title=excluded.title,
          updated_at=datetime('now')
        """,
        (title,),
    )
    await db.commit()
    cur = await db.execute("SELECT id FROM catalog_items WHERE path='/'")
    row = await cur.fetchone()
    return int(row[0])


async def fetch_catalog_children(
    db: aiosqlite.Connection,
    parent_id: int,
    offset: int,
    limit: int,
) -> list[dict]:
    cur = await db.execute(
        """
        SELECT id, kind, title, path
        FROM catalog_items
        WHERE parent_id=?
        ORDER BY kind DESC, title ASC
        LIMIT ? OFFSET ?
        """,
        (parent_id, limit, offset),
    )
    rows = await cur.fetchall()
    return [
        {"id": int(r[0]), "kind": r[1], "title": r[2], "path": r[3]}
        for r in rows
    ]


async def count_catalog_children(db: aiosqlite.Connection, parent_id: int) -> int:
    cur = await db.execute("SELECT COUNT(*) FROM catalog_items WHERE parent_id=?", (parent_id,))
    row = await cur.fetchone()
    return int(row[0] or 0)
