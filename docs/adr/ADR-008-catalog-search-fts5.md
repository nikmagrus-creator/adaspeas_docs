# ADR-008: Поиск по каталогу через SQLite FTS5 + search_sessions

Актуально на: 2026-02-10 20:45 MSK

- Status: Accepted
- Date (MSK): 2026-02-08 22:15 MSK
- Deciders: Nikolay, ChatGPT
- Technical Story: Milestone 3 — поиск по каталогу (/search)

## Context
Нужен быстрый поиск по каталогу (IDEA-007).
Inline‑кнопки Telegram ограничивают `callback_data` 1–64 байт, поэтому «зашивать» запрос (или scope+query) прямо в callback нельзя при реальных строках.

Требования:
- быстрый поиск по большим деревьям;
- пагинация результатов;
- callback_data должен содержать только короткий токен.

## Decision
1) Добавляем внешний FTS5 индекс:
   - `catalog_items_fts(title, path, content='catalog_items', content_rowid='id')`.
2) Синхронизацию индекса обеспечиваем триггерами INSERT/UPDATE/DELETE на `catalog_items`.
3) Для пагинации результатов поиска используем таблицу `search_sessions(token, tg_user_id, scope_path, query, created_at)`.
   - В callback передаём только `s:<token>:<offset>`.

## Consequences
- Поиск быстрый на больших каталогах (bm25 ранжирование), с fallback на `LIKE` если FTS5 недоступен в сборке SQLite.
- Вводится TTL для `search_sessions` (чистим по времени).
- В миграциях требуется `rebuild` индекса для существующих данных.

## Links
- Chatlog: `docs/CHATLOG_RU.md` (2026-02-08 22:15 MSK)
- Related ADRs: ADR-006 (inline nav + parent_path), ADR-007 (UI читает только SQLite)
- Changelog: `CHANGELOG.md`
- SQLite FTS5: https://sqlite.org/fts5.html
- Telegram Bot API (лимиты callback_data/схема callback-передачи): https://core.telegram.org/bots/api
