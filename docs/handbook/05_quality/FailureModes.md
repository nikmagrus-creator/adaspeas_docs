---
doc_id: DOC-FM
title: Failure Modes
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: 'Таблица отказов: симптом → причина → предотвращение → обнаружение → восстановление.'
inputs:
- 01_product/PRD.md
- 04_ops/ObservabilitySpec.md
- 03_arch/StateMachines.md
outputs:
- Failure modes table
---

# Failure Modes

| Симптом | Причина | Предотвращение | Обнаружение | Восстановление |
|---|---|---|---|---|
| Навигация > 500ms | нет кэша/плохие индексы | Redis cache + индексы SQLite | p95 latency metric | прогреть кэш, добавить индекс |
| Скачивание не начинается | очередь переполнена | rate-limit + queue cap | queue_depth alert | throttle, увеличить worker |
| Ошибки YD 401 | протух токен | auto-refresh + ротация | oauth alert | обновить refresh token |
| job завис в RUNNING | worker crash | heartbeat + reconcile | heartbeat alert | вернуть в QUEUED/FAIL |
| Файл не доставлен | Telegram timeout | retryable mapping | error spike | retry/backoff, снизить параллелизм |
| Утечка PII в логах | неправильное логирование | redaction правила | grep test + audit | purge logs, hotfix |
| GC spool не работает | баг/конфиг | TTL + лимиты | spool_usage alert | ручная очистка, fix GC |
