---
doc_id: DOC-DATA
title: Data Model
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: Схема данных (SQLite) и ключи/индексы/инварианты; опора на PRD.
inputs:
- 01_product/PRD.md
- 03_arch/StateMachines.md
outputs:
- SQLite DDL
- Indexes
- Invariants
- Migration rules
---

# Data Model (SQLite)

## 0) Principles
- SQLite в WAL режиме.
- Все записи изменяем транзакционно.
- Никаких секретов в логах; токены в отдельной таблице с минимальным доступом.

## 1) Core entities

### 1.1 users
```sql
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  telegram_chat_id INTEGER NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK(role IN ('USER','ADMIN')),
  status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','BLOCKED','DELETED')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
```

### 1.2 invites
```sql
CREATE TABLE IF NOT EXISTS invites (
  invite_id INTEGER PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK(role IN ('USER','ADMIN')),
  expires_at TEXT NOT NULL,
  used_at TEXT,
  used_by_user_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_invites_expires ON invites(expires_at);
```

### 1.3 categories
```sql
CREATE TABLE IF NOT EXISTS categories (
  category_id INTEGER PRIMARY KEY,
  parent_id INTEGER,
  name TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(parent_id) REFERENCES categories(category_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_categories_parent_name ON categories(parent_id, name);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id, sort_order);
```

### 1.4 files
```sql
CREATE TABLE IF NOT EXISTS files (
  file_id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  yd_path TEXT NOT NULL, -- canonical reference in Yandex Disk
  size_bytes INTEGER NOT NULL,
  checksum TEXT, -- optional
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(category_id) REFERENCES categories(category_id)
);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category_id, name);
```

### 1.5 favorites
```sql
CREATE TABLE IF NOT EXISTS favorites (
  user_id INTEGER NOT NULL,
  file_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(user_id, file_id),
  FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(file_id) REFERENCES files(file_id)
);
```

### 1.6 jobs
```sql
CREATE TABLE IF NOT EXISTS jobs (
  job_id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  file_id INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN (
    'QUEUED','CLAIMED','DOWNLOADING','STREAMING','DELIVERED','FAILED','CANCELLED','EXPIRED'
  )),
  attempt INTEGER NOT NULL DEFAULT 0,
  last_error_code TEXT,
  last_error_message TEXT,
  idempotency_key TEXT NOT NULL,
  heartbeat_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_idempotency ON jobs(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, updated_at);
```

### 1.7 audit_log
```sql
CREATE TABLE IF NOT EXISTS audit_log (
  audit_id INTEGER PRIMARY KEY,
  actor_user_hash TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, created_at);
```

### 1.8 oauth_tokens (YD)
```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
  token_id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL CHECK(provider IN ('YANDEX_DISK')),
  refresh_token TEXT NOT NULL,
  access_token TEXT,
  access_expires_at TEXT,
  updated_at TEXT NOT NULL
);
```

## 2) Invariants

- `telegram_chat_id` уникален.
- Категория уникальна по `(parent_id, name)`.
- Job уникален по `idempotency_key` (dedup).
- Retry: `attempt` не превышает 3 (enforced logic-level).
- File size must be `<= 2GB` (enforced logic-level).

## 3) Migrations
- Таблица `schema_version(version INTEGER)` (или pragma user_version).
- Обновления только вперёд; rollback через backup DB или миграцию N-1, если требуется.
