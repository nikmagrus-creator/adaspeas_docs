---
doc_id: ADR-0001
title: 'Queue source of truth: SQLite vs Redis'
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
---

# ADR-0001: Queue source of truth: SQLite vs Redis

## Status
ACCEPTED (2026-02-03)

## Context
PRD требует: Redis queue + SQLite WAL, RTO < 1 мин, retry ≤ 3. Redis хорош как транспорт, но не гарантирует долговременную консистентность, а crash/restart не должен терять “что случилось” с job.

## Decision
- **SQLite является источником истины** для job state и попыток (attempts).
- **Redis используется как транспорт**: очередь содержит только `job_id` (и минимум метаданных для маршрутизации, без секретов).
- Любая обработка job начинается и заканчивается транзакциями в SQLite.

## Alternatives
1) Redis как SoT (хранить state в Redis): быстрее, но риск потери/несогласованности, сложнее миграции/аудит.
2) Только SQLite без Redis: проще, но хуже масштабирование и backpressure; сложнее обеспечить SLO навигации и burst enqueue.

## Consequences
- Нужны индексы и WAL для SQLite.
- Нужна процедура “reconcile” при старте worker (подбор зависших jobs).
- Redis может быть очищен без потери корректного состояния (queue восстанавливается из SQLite при необходимости).
