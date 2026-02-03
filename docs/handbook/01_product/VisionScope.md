---
doc_id: DOC-VISION
title: Vision & Scope
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: Видение продукта и границы scope на основе PRD.
inputs:
- 01_product/PRD.md
outputs:
- Scope boundaries
- Non-goals
---

# Vision & Scope

## Vision
Закрытый Telegram-доступ к документам, где пользователь быстро находит файл и получает его в чат, а администратор управляет каталогом и доступом.

## In-scope (v1)
- Древовидные категории + breadcrumb + кнопки домой/назад.
- Inline поиск.
- Избранное.
- Скачивание в Telegram через очередь задач (retry ≤ 3, параллелизм ограничен).
- Admin: CRUD категорий/файлов, инвайты, блокировка, audit log.
- Интеграции: Yandex Disk OAuth + API; Local Bot API; Redis; SQLite.
- Observability: /status, алерты, структурные логи без PII.

## Out-of-scope (v1)
- Мульти-тенантность/несколько “workspaces”.
- Полнотекстовый поиск по содержимому документов.
- Web UI.
- Версионирование документов как в DMS.
- Репликация/шардинг SQLite.

## Constraints
- Файлы не храним на VPS постоянно.
- Лимит файла ≤ 2GB.
- Навигация целится в < 500ms.
