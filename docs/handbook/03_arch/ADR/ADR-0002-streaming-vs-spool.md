---
doc_id: ADR-0002
title: Streaming vs temporary spool for file delivery
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
---

# ADR-0002: Streaming vs temporary spool for file delivery

## Status
ACCEPTED (2026-02-03)

## Context
PRD: “Streaming: Yandex Disk → Local Bot API → Telegram” и “без постоянного хранения файлов на VPS”, лимит файла ≤ 2GB. На практике Telegram API иногда требует file path (для некоторых методов/режимов), а сеть может быть нестабильной.

## Decision
- **Основной режим: streaming** (YD → Worker → Local Bot API → Telegram).
- **Fallback: temporary spool** в /tmp с TTL и жёстким лимитом размера, когда API/SDK требует filepath или при нестабильном стриме.
- Spool строго краткоживущий: удаление после отправки или по TTL, не индексируется и не доступен извне.

## Alternatives
1) Всегда spool: проще интеграция, но нарушает constraint (“не хранить”), увеличивает риск утечки и место на диске.
2) Только streaming без spool: чище, но повышает риск невозможности доставки в отдельных edge cases.

## Consequences
- Нужен GC для /tmp spool + метрика/алерт “spool usage”.
- Нужны таймауты/бекпрешер для стрима, чтобы не подвесить worker.
- Audit log фиксирует факт отправки, но не путь к файлу.
