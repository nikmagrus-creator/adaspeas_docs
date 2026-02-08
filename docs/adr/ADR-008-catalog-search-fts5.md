# ADR-008: Поиск по каталогу через SQLite FTS5 + search_sessions

Дата: 2026-02-08

## Контекст
Нужен быстрый поиск по каталогу (IDEA-007). Inline-кнопки Telegram ограничивают `callback_data` до 64 байт, поэтому “зашивать” запрос прямо в callback нельзя при реальных строках.

## Решение
1) Добавляем внешний FTS5 индекс `catalog_items_fts(title, path, content='catalog_items', content_rowid='id')`.
2) Синхронизацию индекса обеспечиваем триггерами INSERT/UPDATE/DELETE на `catalog_items`.
3) Для пагинации результатов поиска используем таблицу `search_sessions(token, tg_user_id, scope_path, query, created_at)`.
   - В callback передаём только `s:<token>:<offset>`.

## Последствия
- Поиск быстрый на больших каталогах (bm25 ранжирование), с fallback на `LIKE` если FTS5 недоступен в сборке SQLite.
- Вводится TTL для search_sessions (чистим по времени).
- В миграциях требуется `rebuild` индекса для существующих данных.
