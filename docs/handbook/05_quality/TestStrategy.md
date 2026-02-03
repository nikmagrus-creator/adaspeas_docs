---
doc_id: DOC-TEST
title: Test Strategy
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: 'Стратегия тестирования на базе PRD: функционал + NFR + edge cases.'
inputs:
- 01_product/PRD.md
- 03_arch/StateMachines.md
outputs:
- Test matrix
- DoD
---

# Test Strategy

## 1) Levels

- Unit: RBAC, catalog, idempotency key, error mapping.
- Integration: SQLite migrations, Redis queue, worker reconcile, YD client (mock), Local Bot API (mock).
- E2E (staging): navigation/search/download с реальным Telegram и тестовым YD.

## 2) Core test matrix (из PRD)

Навигация:
- breadcrumb корректен
- back/home работает
- p95 latency < 500ms на тестовом наборе (10k файлов)

Скачивание:
- очередь, параллелизм ограничен
- retry ≤ 3
- >2GB сообщает пользователю
- streaming работает, spool fallback очищается

Admin:
- CRUD категорий/файлов с подтверждением
- invite flow + блокировка
- audit log пишется

Observability:
- /status доступен только admin
- метрики обновляются
- логи без PII

## 3) Failure & recovery

- crash mid-download → job возвращается в QUEUED или FAIL по attempt
- oauth expired → auto-refresh + алерт
- queue overflow → throttle + алерт

## 4) Definition of Done
- Все PRD acceptance критерии покрыты тестами.
- Нет PII/секретов в логах (автотест grep).
- Документы-гейты имеют статус DONE.
