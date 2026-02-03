---
doc_id: DOC-RUNBOOK
title: Runbook
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: 'Операционные процедуры: диагностика, восстановление, частые инциденты.'
inputs:
- 04_ops/ObservabilitySpec.md
- 01_product/PRD.md
outputs:
- Incident procedures
---

# Runbook

## 1) Основные команды

- `/status` (admin-only): очередь, heartbeat, токены, ошибки.
- `/history` (если реализовано): последние jobs.

## 2) Инциденты

### 2.1 Queue overflow
Symptoms: рост `queue_depth_current`, пользователи жалуются на задержки.
Actions:
1) включить throttle/rate-limit (если конфиг).
2) увеличить worker parallelism (в пределах ресурсов).
3) проверить не спамит ли один пользователь (audit).
4) если Redis деградирует: перезапуск Redis, затем reconcile jobs из SQLite.

### 2.2 OAuth expired / cannot refresh
Symptoms: алерт `oauth_token_expires_in_seconds < 0` или рост 401/403 от YD.
Actions:
1) заблокировать выдачу (fail fast) + сообщение админам.
2) обновить refresh token (ручная процедура).
3) проверить, что токены не попали в логи.

### 2.3 Worker stuck (heartbeat missing)
Actions:
1) посмотреть process health.
2) перезапустить worker.
3) reconcile: jobs с протухшим heartbeat вернуть в QUEUED или FAIL по attempt.

### 2.4 Telegram delivery failures
Symptoms: рост failed, таймауты.
Actions:
1) проверить Local Bot API доступность.
2) уменьшить параллелизм.
3) включить fallback spool (если выключен) и проверить disk usage.

## 3) Data safety

- Перед миграцией: backup SQLite.
- Логи: ротация, проверка redaction.
