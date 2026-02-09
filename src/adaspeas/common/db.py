from __future__ import annotations

import aiosqlite
import re
import uuid


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


# v5: soft-delete + "last seen" timestamp for catalog sync
MIGRATION_V5 = """
ALTER TABLE catalog_items ADD COLUMN seen_at TEXT;
ALTER TABLE catalog_items ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_catalog_deleted_parent ON catalog_items(is_deleted, parent_path);
"""

# v6: access control (Milestone 2): user statuses, notes, expiry and 24h warning marker.
MIGRATION_V6 = """
ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'guest';
ALTER TABLE users ADD COLUMN user_note TEXT;
ALTER TABLE users ADD COLUMN expires_at TEXT;
ALTER TABLE users ADD COLUMN warned_24h_at TEXT;
ALTER TABLE users ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));
CREATE INDEX IF NOT EXISTS idx_users_status_expires ON users(status, expires_at);
"""


# v7: operations transparency (Milestone 3): download audit log + indexes for stats.
MIGRATION_V7 = """
CREATE TABLE IF NOT EXISTS download_audit (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  job_id INTEGER NOT NULL UNIQUE,
  tg_chat_id INTEGER NOT NULL,
  tg_user_id INTEGER NOT NULL,
  catalog_item_id INTEGER NOT NULL,
  result TEXT NOT NULL CHECK(result IN ('succeeded','failed')),
  mode TEXT,
  bytes INTEGER,
  error TEXT,
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
  FOREIGN KEY (catalog_item_id) REFERENCES catalog_items(id)
);

CREATE INDEX IF NOT EXISTS idx_download_audit_created ON download_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_download_audit_user_created ON download_audit(tg_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_download_audit_item_created ON download_audit(catalog_item_id, created_at);

-- Jobs: speed up admin queries by time window.
CREATE INDEX IF NOT EXISTS idx_jobs_type_created ON jobs(job_type, created_at);
"""

# v8: catalog search (IDEA-007): full-text search index for title/path (FTS5, external content).
MIGRATION_V8 = """
CREATE VIRTUAL TABLE IF NOT EXISTS catalog_items_fts USING fts5(
  title,
  path,
  content='catalog_items',
  content_rowid='id'
);

-- Keep FTS index consistent with catalog_items.
CREATE TRIGGER IF NOT EXISTS catalog_items_fts_ai AFTER INSERT ON catalog_items BEGIN
  INSERT INTO catalog_items_fts(rowid, title, path) VALUES (new.id, new.title, new.path);
END;
CREATE TRIGGER IF NOT EXISTS catalog_items_fts_ad AFTER DELETE ON catalog_items BEGIN
  INSERT INTO catalog_items_fts(catalog_items_fts, rowid, title, path) VALUES('delete', old.id, old.title, old.path);
END;
CREATE TRIGGER IF NOT EXISTS catalog_items_fts_au AFTER UPDATE ON catalog_items BEGIN
  INSERT INTO catalog_items_fts(catalog_items_fts, rowid, title, path) VALUES('delete', old.id, old.title, old.path);
  INSERT INTO catalog_items_fts(rowid, title, path) VALUES (new.id, new.title, new.path);
END;

-- Ensure index is populated / consistent for existing rows.
INSERT INTO catalog_items_fts(catalog_items_fts) VALUES('rebuild');
"""

# v9: catalog search sessions to keep callback_data small (Telegram limit is 64 bytes).
MIGRATION_V9 = """
CREATE TABLE IF NOT EXISTS search_sessions (
  token TEXT PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  tg_user_id INTEGER NOT NULL,
  scope_path TEXT NOT NULL,
  query TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_sessions_user_created ON search_sessions(tg_user_id, created_at);
"""


# v10: admin sessions for /users (keep callback_data short for Telegram).
MIGRATION_V10 = """
CREATE TABLE IF NOT EXISTS admin_sessions (
  token TEXT PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  tg_user_id INTEGER NOT NULL,
  query TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_user_created ON admin_sessions(tg_user_id, created_at);
"""





TARGET_SCHEMA_VERSION = 10
MIGRATIONS: dict[int, str] = {
    2: MIGRATION_V2,
    3: MIGRATION_V3,
    4: MIGRATION_V4,
    5: MIGRATION_V5,
    6: MIGRATION_V6,
    7: MIGRATION_V7,
    8: MIGRATION_V8,
    9: MIGRATION_V9,
    10: MIGRATION_V10,
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


async def get_schema_version(db: aiosqlite.Connection) -> int:
    """Return current schema version (0 if DB is uninitialized)."""
    return await _get_schema_version(db)


async def count_rows(db: aiosqlite.Connection, table: str) -> int:
    """Best-effort row count for diagnostics."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", table or ""):
        raise ValueError("Invalid table name")
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    row = await cur.fetchone()
    return int(row[0] or 0)


async def group_count(db: aiosqlite.Connection, table: str, column: str) -> dict[str, int]:
    """Best-effort grouped counts for diagnostics."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", table or "") or not re.fullmatch(r"[A-Za-z0-9_]+", column or ""):
        raise ValueError("Invalid table/column")
    cur = await db.execute(f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}")
    out: dict[str, int] = {}
    async for row in cur:
        out[str(row[0])] = int(row[1] or 0)
    return out


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



# --- Access control (Milestone 2) ---

USER_STATUSES = {"guest", "pending", "active", "expired", "blocked"}


def _now_sqlite_utc() -> str:
    # Keep the same sortable format SQLite uses for datetime('now').
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


async def fetch_user_by_tg_user_id(db: aiosqlite.Connection, tg_user_id: int) -> dict | None:
    cur = await db.execute(
        "SELECT id, tg_user_id, created_at, status, user_note, expires_at, warned_24h_at, updated_at FROM users WHERE tg_user_id=?",
        (tg_user_id,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "tg_user_id": int(row[1]),
        "created_at": row[2],
        "status": row[3] or "guest",
        "user_note": row[4],
        "expires_at": row[5],
        "warned_24h_at": row[6],
        "updated_at": row[7],
    }


async def set_user_note(db: aiosqlite.Connection, tg_user_id: int, note: str) -> None:
    await db.execute(
        "UPDATE users SET user_note=?, updated_at=datetime('now') WHERE tg_user_id=?",
        (note, tg_user_id),
    )
    await db.commit()


async def set_user_status(
    db: aiosqlite.Connection,
    tg_user_id: int,
    status: str,
    *,
    expires_at: str | None = None,
) -> None:
    status = (status or "").strip().lower()
    if status not in USER_STATUSES:
        raise ValueError(f"Unknown user status: {status}")
    await db.execute(
        "UPDATE users SET status=?, expires_at=?, warned_24h_at=NULL, updated_at=datetime('now') WHERE tg_user_id=?",
        (status, expires_at, tg_user_id),
    )
    await db.commit()


async def activate_user(db: aiosqlite.Connection, tg_user_id: int, ttl_days: int) -> None:
    ttl_days = int(ttl_days)
    if ttl_days <= 0:
        ttl_days = 1
    # Store expiry in SQLite-friendly format (UTC).
    from datetime import datetime, timedelta, timezone
    expires = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=ttl_days)
    expires_at = expires.strftime("%Y-%m-%d %H:%M:%S")
    await set_user_status(db, tg_user_id, "active", expires_at=expires_at)


async def extend_user(db: aiosqlite.Connection, tg_user_id: int, add_days: int) -> None:
    add_days = int(add_days)
    if add_days <= 0:
        add_days = 1
    u = await fetch_user_by_tg_user_id(db, tg_user_id)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if not u or not u.get("expires_at"):
        base = now
    else:
        try:
            base = datetime.strptime(str(u["expires_at"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            base = now
        if base < now:
            base = now
    expires = base + timedelta(days=add_days)
    expires_at = expires.strftime("%Y-%m-%d %H:%M:%S")
    await set_user_status(db, tg_user_id, "active", expires_at=expires_at)


async def list_users_page(db: aiosqlite.Connection, *, limit: int = 200, offset: int = 0) -> tuple[list[dict], bool]:
    """Return users page ordered by updated_at DESC. has_more is best-effort."""
    limit = max(1, int(limit))
    offset = max(0, int(offset))
    limit_plus = limit + 1
    cur = await db.execute(
        "SELECT tg_user_id, created_at, status, user_note, expires_at, warned_24h_at, updated_at FROM users ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (int(limit_plus), int(offset)),
    )
    rows = await cur.fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "tg_user_id": int(r[0]),
                "created_at": r[1],
                "status": r[2] or "guest",
                "user_note": r[3],
                "expires_at": r[4],
                "warned_24h_at": r[5],
                "updated_at": r[6],
            }
        )
    return out, has_more


async def list_users(db: aiosqlite.Connection, limit: int = 200, offset: int = 0) -> list[dict]:
    """Backward-compatible wrapper."""
    users, _more = await list_users_page(db, limit=limit, offset=offset)
    return users

# --- Admin UI sessions and user search (Milestone 2 UX) ---

async def cleanup_admin_sessions(db: aiosqlite.Connection, ttl_sec: int) -> None:
    if ttl_sec <= 0:
        return
    await db.execute(
        "DELETE FROM admin_sessions WHERE created_at < datetime('now', ?)",
        (f"-{int(ttl_sec)} seconds",),
    )
    await db.commit()


async def create_admin_session(
    db: aiosqlite.Connection,
    *,
    tg_user_id: int,
    query: str | None,
    ttl_sec: int = 3600,
) -> str:
    await cleanup_admin_sessions(db, ttl_sec)
    token = uuid.uuid4().hex[:16]
    await db.execute(
        "INSERT INTO admin_sessions(token, tg_user_id, query) VALUES (?,?,?)",
        (token, int(tg_user_id), (query or "").strip() or None),
    )
    await db.commit()
    return token


async def fetch_admin_session(db: aiosqlite.Connection, token: str) -> dict | None:
    cur = await db.execute(
        "SELECT token, created_at, tg_user_id, query FROM admin_sessions WHERE token=?",
        (token,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return {"token": str(row[0]), "created_at": row[1], "tg_user_id": int(row[2]), "query": row[3]}


async def search_users(
    db: aiosqlite.Connection,
    *,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], bool]:
    q = (query or "").strip()
    if not q:
        return [], False

    limit = max(1, int(limit))
    offset = max(0, int(offset))
    limit_plus = limit + 1

    # Numeric search: tg_user_id exact or prefix.
    if q.isdigit():
        like = q + "%"
        cur = await db.execute(
            """
            SELECT tg_user_id, created_at, status, user_note, expires_at, warned_24h_at, updated_at
            FROM users
            WHERE tg_user_id = ?
               OR CAST(tg_user_id AS TEXT) LIKE ?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (int(q), like, int(limit_plus), int(offset)),
        )
    else:
        like = f"%{_like_escape(q)}%"
        cur = await db.execute(
            """
            SELECT tg_user_id, created_at, status, user_note, expires_at, warned_24h_at, updated_at
            FROM users
            WHERE status LIKE ? ESCAPE '\'
               OR (user_note IS NOT NULL AND user_note LIKE ? ESCAPE '\')
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (like, like, int(limit_plus), int(offset)),
        )

    rows = await cur.fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "tg_user_id": int(r[0]),
                "created_at": r[1],
                "status": r[2] or "guest",
                "user_note": r[3],
                "expires_at": r[4],
                "warned_24h_at": r[5],
                "updated_at": r[6],
            }
        )
    return out, has_more


async def expire_users(db: aiosqlite.Connection) -> int:
    # Mark active users with past expiry as expired.
    cur = await db.execute(
        "UPDATE users SET status='expired', updated_at=datetime('now') WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= datetime('now')"
    )
    await db.commit()
    return int(cur.rowcount or 0)


async def fetch_users_expiring_within(db: aiosqlite.Connection, warn_before_sec: int) -> list[dict]:
    warn_before_sec = int(warn_before_sec)
    if warn_before_sec <= 0:
        warn_before_sec = 86400
    # SQLite does not accept parameterized modifiers, so build a safe string.
    minutes = max(1, int(warn_before_sec // 60))
    boundary_expr = f"datetime('now', '+{minutes} minutes')"
    cur = await db.execute(
        f"""
        SELECT tg_user_id, status, user_note, expires_at
        FROM users
        WHERE status='active'
          AND expires_at IS NOT NULL
          AND expires_at <= {boundary_expr}
          AND (warned_24h_at IS NULL)
        ORDER BY expires_at ASC
        LIMIT 200
        """
    )
    rows = await cur.fetchall()
    out=[]
    for r in rows:
        out.append({"tg_user_id": int(r[0]), "status": r[1], "user_note": r[2], "expires_at": r[3]})
    return out


async def mark_user_warned_24h(db: aiosqlite.Connection, tg_user_id: int) -> None:
    await db.execute(
        "UPDATE users SET warned_24h_at=datetime('now'), updated_at=datetime('now') WHERE tg_user_id=?",
        (tg_user_id,),
    )
    await db.commit()

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
        SELECT id, path, kind, title, yandex_id, size_bytes, tg_file_id, tg_file_unique_id, parent_path, seen_at, is_deleted
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
        "seen_at": row[9],
        "is_deleted": int(row[10] or 0),
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
        INSERT INTO catalog_items(path, kind, title, yandex_id, size_bytes, parent_path, updated_at, seen_at, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 0)
        ON CONFLICT(path) DO UPDATE SET
          kind=excluded.kind,
          title=excluded.title,
          yandex_id=excluded.yandex_id,
          size_bytes=excluded.size_bytes,
          parent_path=excluded.parent_path,
          updated_at=datetime('now'),
          seen_at=datetime('now'),
          is_deleted=0
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
        SELECT id, path, kind, title, yandex_id, size_bytes, tg_file_id, tg_file_unique_id, parent_path, seen_at, is_deleted
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
        "seen_at": row[9],
        "is_deleted": int(row[10] or 0),
    }


async def fetch_children(
    db: aiosqlite.Connection,
    parent_path: str | None,
    *,
    limit: int = 60,
    offset: int = 0,
) -> list[dict]:
    """Fetch immediate children for a folder path."""
    cur = await db.execute(
        """
        SELECT id, kind, title, size_bytes
        FROM catalog_items
        WHERE parent_path IS ?
          AND is_deleted=0
        ORDER BY kind DESC, title ASC
        LIMIT ? OFFSET ?
        """,
        (parent_path, int(limit), int(offset)),
    )
    rows = await cur.fetchall()
    return [
        {"id": int(r[0]), "kind": r[1], "title": r[2], "size_bytes": r[3]}
        for r in rows
    ]


async def count_children(db: aiosqlite.Connection, parent_path: str | None) -> int:
    cur = await db.execute(
        """
        SELECT COUNT(*)
        FROM catalog_items
        WHERE parent_path IS ?
          AND is_deleted=0
        """,
        (parent_path,),
    )
    row = await cur.fetchone()
    return int(row[0] or 0)



# --- Catalog search (IDEA-007) ---

def _fts_query_from_user(q: str) -> str:
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", (q or "").strip())
    tokens = [t for t in tokens if t][:8]
    if not tokens:
        return ""
    return " AND ".join([f"{t}*" for t in tokens])


def _like_escape(q: str) -> str:
    return (q or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _scope_like(scope_path: str) -> str:
    p = (scope_path or "/").rstrip("/") or "/"
    if p == "/":
        return "/%"
    return p + "/%"


async def cleanup_search_sessions(db: aiosqlite.Connection, ttl_sec: int) -> None:
    if ttl_sec <= 0:
        return
    await db.execute(
        "DELETE FROM search_sessions WHERE created_at < datetime('now', ?)",
        (f"-{int(ttl_sec)} seconds",),
    )
    await db.commit()


async def create_search_session(
    db: aiosqlite.Connection,
    *,
    tg_user_id: int,
    query: str,
    scope_path: str,
    ttl_sec: int = 3600,
) -> str:
    await cleanup_search_sessions(db, ttl_sec)
    token = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO search_sessions(token, tg_user_id, scope_path, query) VALUES (?,?,?,?)",
        (token, int(tg_user_id), (scope_path or "/"), (query or "").strip()),
    )
    await db.commit()
    return token


async def fetch_search_session(db: aiosqlite.Connection, token: str) -> dict | None:
    cur = await db.execute(
        "SELECT token, created_at, tg_user_id, scope_path, query FROM search_sessions WHERE token=?",
        (token,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return {
        "token": str(row[0]),
        "created_at": row[1],
        "tg_user_id": int(row[2]),
        "scope_path": str(row[3]),
        "query": str(row[4]),
    }


async def search_catalog_items(
    db: aiosqlite.Connection,
    *,
    query: str,
    scope_path: str,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict], bool]:
    q = (query or "").strip()
    if not q:
        return [], False

    scope_like = _scope_like(scope_path)
    limit = max(1, int(limit))
    offset = max(0, int(offset))
    limit_plus = limit + 1

    fts_q = _fts_query_from_user(q)
    if fts_q:
        try:
            cur = await db.execute(
                """
                SELECT c.id, c.kind, c.title, c.size_bytes, c.path
                FROM catalog_items_fts f
                JOIN catalog_items c ON c.id = f.rowid
                WHERE f MATCH ?
                  AND c.is_deleted=0
                  AND c.path LIKE ?
                ORDER BY bm25(f), c.kind DESC, c.title ASC
                LIMIT ? OFFSET ?
                """,
                (fts_q, scope_like, int(limit_plus), int(offset)),
            )
            rows = await cur.fetchall()
            items = [
                {"id": int(r[0]), "kind": r[1], "title": r[2], "size_bytes": r[3], "path": r[4]}
                for r in rows
            ]
            has_more = len(items) > limit
            return items[:limit], has_more
        except Exception:
            pass

    like = f"%{_like_escape(q)}%"
    cur = await db.execute(
        """
        SELECT id, kind, title, size_bytes, path
        FROM catalog_items
        WHERE is_deleted=0
          AND path LIKE ?
          AND title LIKE ? ESCAPE '\\'
        ORDER BY kind DESC, title ASC
        LIMIT ? OFFSET ?
        """,
        (scope_like, like, int(limit_plus), int(offset)),
    )
    rows = await cur.fetchall()
    items = [{"id": int(r[0]), "kind": r[1], "title": r[2], "size_bytes": r[3], "path": r[4]} for r in rows]
    has_more = len(items) > limit
    return items[:limit], has_more


async def db_now(db: aiosqlite.Connection) -> str:
    """Return SQLite's datetime('now') string for lexicographically comparable timestamps."""
    cur = await db.execute("SELECT datetime('now')")
    row = await cur.fetchone()
    return str(row[0]) if row and row[0] else ""


async def mark_deleted_not_seen(db: aiosqlite.Connection, root_path: str, seen_threshold: str) -> int:
    """Mark as deleted everything under root that wasn't seen since seen_threshold."""
    root = (root_path or "/").rstrip("/") or "/"
    if root == "/":
        like = "/%"
        args = (seen_threshold, like, root)
        q = """
        UPDATE catalog_items
        SET is_deleted=1, updated_at=datetime('now')
        WHERE (seen_at IS NULL OR seen_at < ?)
          AND path LIKE ?
          AND path != ?
          AND is_deleted=0
        """
    else:
        like = root.rstrip("/") + "/%"
        args = (seen_threshold, root, like, root)
        q = """
        UPDATE catalog_items
        SET is_deleted=1, updated_at=datetime('now')
        WHERE (seen_at IS NULL OR seen_at < ?)
          AND (path = ? OR path LIKE ?)
          AND path != ?
          AND is_deleted=0
        """
    cur = await db.execute(q, args)
    await db.commit()
    return int(cur.rowcount or 0)


async def has_active_sync_job(db: aiosqlite.Connection) -> bool:
    cur = await db.execute(
        """
        SELECT 1 FROM jobs
        WHERE job_type='sync_catalog'
          AND state IN ('queued','running')
        LIMIT 1
        """,
    )
    row = await cur.fetchone()
    return bool(row)


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


# --- Operations transparency (Milestone 3): download audit + admin stats ---

async def insert_download_audit(
    db: aiosqlite.Connection,
    *,
    job_id: int,
    tg_chat_id: int,
    tg_user_id: int,
    catalog_item_id: int,
    result: str,
    mode: str | None = None,
    bytes_sent: int | None = None,
    error: str | None = None,
) -> None:
    result = (result or "").strip().lower()
    if result not in {"succeeded", "failed"}:
        raise ValueError(f"Unknown audit result: {result}")
    await db.execute(
        """
        INSERT INTO download_audit(job_id, tg_chat_id, tg_user_id, catalog_item_id, result, mode, bytes, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO NOTHING
        """,
        (
            int(job_id),
            int(tg_chat_id),
            int(tg_user_id),
            int(catalog_item_id),
            result,
            mode,
            (int(bytes_sent) if bytes_sent is not None else None),
            error,
        ),
    )
    await db.commit()


async def fetch_recent_download_audit(
    db: aiosqlite.Connection,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    cur = await db.execute(
        """
        SELECT
          a.created_at,
          a.job_id,
          a.tg_chat_id,
          a.tg_user_id,
          a.catalog_item_id,
          a.result,
          a.mode,
          a.bytes,
          a.error,
          c.path,
          c.title,
          c.size_bytes
        FROM download_audit a
        JOIN catalog_items c ON c.id = a.catalog_item_id
        ORDER BY a.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (int(limit), int(offset)),
    )
    rows = await cur.fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "created_at": r[0],
                "job_id": int(r[1]),
                "tg_chat_id": int(r[2]),
                "tg_user_id": int(r[3]),
                "catalog_item_id": int(r[4]),
                "result": r[5],
                "mode": r[6],
                "bytes": r[7],
                "error": r[8],
                "path": r[9],
                "title": r[10],
                "size_bytes": r[11],
            }
        )
    return out


def _sqlite_since_expr_minutes(minutes: int) -> str:
    minutes = int(minutes)
    if minutes <= 0:
        minutes = 60
    # SQLite does not accept parameterized datetime modifiers.
    return f"datetime('now', '-{minutes} minutes')"


async def count_download_audit_since(
    db: aiosqlite.Connection,
    *,
    since_minutes: int,
) -> dict[str, int]:
    since_expr = _sqlite_since_expr_minutes(since_minutes)
    cur = await db.execute(
        f"""
        SELECT result, COUNT(*)
        FROM download_audit
        WHERE created_at >= {since_expr}
        GROUP BY result
        """
    )
    rows = await cur.fetchall()
    out: dict[str, int] = {"succeeded": 0, "failed": 0}
    for r in rows:
        out[str(r[0])] = int(r[1])
    return out


async def top_downloads_since(
    db: aiosqlite.Connection,
    *,
    since_minutes: int,
    limit: int = 10,
) -> list[dict]:
    since_expr = _sqlite_since_expr_minutes(since_minutes)
    cur = await db.execute(
        f"""
        SELECT
          a.catalog_item_id,
          COUNT(*) AS cnt,
          c.path,
          c.title
        FROM download_audit a
        JOIN catalog_items c ON c.id = a.catalog_item_id
        WHERE a.created_at >= {since_expr}
          AND a.result = 'succeeded'
        GROUP BY a.catalog_item_id
        ORDER BY cnt DESC, a.catalog_item_id ASC
        LIMIT ?
        """,
        (int(limit),),
    )
    rows = await cur.fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "catalog_item_id": int(r[0]),
                "count": int(r[1]),
                "path": r[2],
                "title": r[3],
            }
        )
    return out


async def count_users_by_status(db: aiosqlite.Connection) -> dict[str, int]:
    cur = await db.execute(
        """
        SELECT status, COUNT(*)
        FROM users
        GROUP BY status
        """
    )
    rows = await cur.fetchall()
    out: dict[str, int] = {}
    for r in rows:
        out[str(r[0] or "guest")] = int(r[1])
    return out

