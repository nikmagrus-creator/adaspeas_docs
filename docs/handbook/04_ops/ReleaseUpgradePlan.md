---
doc_id: DOC-RELEASE
title: Release & Upgrade Plan
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: Деплой, конфигурация, миграции, rollback.
inputs:
- 03_arch/DataModel.md
- 04_ops/Runbook.md
outputs:
- Release procedure
- Rollback procedure
---

# Release & Upgrade Plan

## 1) Packaging
- Bot + Worker как отдельные сервисы (systemd/docker).
- Redis отдельным сервисом.
- SQLite хранится на диске VPS (volume), WAL включён.

## 2) Config
- ENV: YD OAuth, ADMIN_CHAT_ID, Redis URL, SQLite path, parallelism, rate limits.
- Secrets через файл/secret-store с правами 600.

## 3) Deploy steps
1) Backup SQLite.
2) Apply migrations (schema_version bump).
3) Restart services (bot first, then worker).
4) Verify `/status` health + smoke test: navigation + download.

## 4) Rollback
- Если миграция backward-incompatible: restore SQLite backup.
- Откат к предыдущему бинарю/контейнеру.
- Проверить, что очередь пустая или reconcile из SQLite.

## 5) Upgrade policy
- Поддержка N и N-1 на уровне конфигов.
- Breaking changes только через новый major в документации.
