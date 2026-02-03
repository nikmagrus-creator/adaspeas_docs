---
doc_id: ADR-0003
title: 'Identity model: chat_id, contexts, invite flow'
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
---

# ADR-0003: Identity model: chat_id, contexts, invite flow

## Status
ACCEPTED (2026-02-03)

## Context
PRD описывает роли User/Admin и инвайт-флоу. Telegram даёт chat_id как устойчивый идентификатор, но “юзернеймы” меняются и не годятся. Нужна модель, которая проста, даёт RBAC и не протекает в логи.

## Decision
- Primary key пользователя: **telegram_chat_id** (BIGINT) в SQLite.
- Внешний идентификатор в логах/аудите: **user_hash = sha256(chat_id + salt)**.
- Онбординг: **одноразовый invite code** (TTL), который активирует пользователя и назначает роль (обычно USER).
- Admin роль назначается только существующим Admin (или через bootstrap config).

## Alternatives
1) username как ключ: нестабилен.
2) “контексты” как отдельная сущность (например, workspace): возможно позже; сейчас out-of-scope.

## Consequences
- Нужна таблица invites (code_hash, role, expires_at, used_at).
- Нужен bootstrap admin (env var ADMIN_CHAT_ID) для первого входа.
