---
doc_id: DOC-OBS
title: Observability Spec
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: Метрики/логи/алерты и диагностические интерфейсы, как требует PRD.
inputs:
- 01_product/PRD.md
- 03_arch/StateMachines.md
- 02_security/Privacy.md
outputs:
- Metrics catalog
- Alert rules
- /status contract
---

# Observability Spec

## 1) Metrics

Конвенции:
- counters: `_total`
- gauges: `_current`
- histogram: `_seconds`

### Core
- `jobs_enqueued_total{source}` (bot)
- `jobs_completed_total{result}` result ∈ {delivered,failed,cancelled,expired}
- `jobs_in_state_current{state}`
- `job_attempts_total{result}`

### Latency
- `navigation_latency_seconds` (histogram)
- `download_latency_seconds` (histogram)
- `yd_api_latency_seconds` (histogram)
- `telegram_send_latency_seconds` (histogram)

### Health
- `worker_heartbeat_age_seconds` (gauge)
- `queue_depth_current` (gauge)
- `oauth_token_expires_in_seconds` (gauge)
- `spool_usage_bytes_current` (gauge, если включён fallback)

## 2) Logs (structured)

Минимальная схема:
- `ts`, `level`, `component`, `event`
- `request_id`, `job_id` (если есть)
- `user_hash` (не chat_id)
- `file_id` (не name/path)
- `error_code`, `error_message` (без секретов)

Запрещено:
- OAuth токены, заголовки Authorization
- raw download URLs
- chat_id/user_id в открытом виде

## 3) Alerts (initial set)

- Queue overflow: `queue_depth_current > X` N минут.
- Worker stuck: `worker_heartbeat_age_seconds > T`.
- Download error spike: рост `jobs_completed_total{result="failed"}`.
- OAuth expiring: `oauth_token_expires_in_seconds < 3600`.
- Navigation SLO regression: p95 `navigation_latency_seconds` > 0.5s.

## 4) /status (admin-only)

Endpoint: `/status` (команда бота или HTTP, по реализации)

Возвращает:
- queue_depth
- jobs_in_state breakdown
- worker heartbeat age
- yd token status (expires_in)
- last errors sample (без PII)

RBAC:
- только ADMIN, иначе deny + audit.
