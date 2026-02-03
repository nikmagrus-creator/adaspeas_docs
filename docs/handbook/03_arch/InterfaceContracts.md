---
doc_id: DOC-CONTRACTS
title: Interface Contracts
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: 'Контракты между компонентами: сообщения очереди, таймауты, ошибки, совместимость.'
inputs:
- 03_arch/ArchitectureSpec.md
- 03_arch/StateMachines.md
- 04_ops/ObservabilitySpec.md
outputs:
- Message schemas
- Error mapping
- Timeouts/retries
---

# Interface Contracts

## 1) Bot → Redis Queue (enqueue)

Queue item: только `job_id` (int). Любые чувствительные данные остаются в SQLite.

Idempotency:
- Bot создаёт job с `idempotency_key`.
- Если такой key уже есть, новый enqueue не делается.

Размеры:
- payload минимальный, поэтому ограничение очереди определяется количеством элементов.

## 2) Worker → SQLite (state update)

Транзакционные границы:
- Claim: `QUEUED -> CLAIMED` (в одной транзакции) + `heartbeat_at = now`.
- State changes только через валидные transition rules (см. StateMachines).

Concurrency:
- Один job может быть “claimed” только одним worker (guard: state=QUEUED).
- Optimistic checks через `WHERE job_id=? AND state=?`.

## 3) Worker → Yandex Disk API

Auth:
- OAuth refresh при истечении access token.
- Ошибки маппятся:
  - 401/403 -> non-retryable (если refresh не помог) + alert
  - 404 -> non-retryable
  - 5xx/timeouts -> retryable

Timeouts:
- connect timeout: 5s
- read timeout: 30s (или chunked)

## 4) Worker → Local Bot API / Telegram delivery

Режим:
- default streaming
- fallback spool (tmp path) только внутри worker

Timeouts:
- send init: 10s
- stream chunk: 30s
- overall job: configurable (например 15 мин)

Backpressure:
- ограничение параллелизма worker
- отмена стрима при превышении лимитов

## 5) Admin /status contract (bot command)

Ответ (текст/JSON по реализации) должен включать:
- queue_depth
- jobs_in_state breakdown
- worker heartbeat age
- oauth token expires_in
- top errors (sanitized)

Permissions:
- ADMIN only. Любая попытка USER -> deny + audit.

## 6) Compatibility rules

- Версии схемы SQLite: миграции обязательны при релизе.
- Изменение state machine или queue semantics -> новый ADR + обновление docs.
