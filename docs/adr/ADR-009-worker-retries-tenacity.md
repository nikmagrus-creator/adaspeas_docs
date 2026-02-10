# ADR-009: Ретраи/backoff для Telegram/Yandex через tenacity

Актуально на: 2026-02-10 22:20 MSK

- Status: Accepted
- Date (MSK): 2026-02-08 22:15 MSK
- Deciders: Nikolay, ChatGPT
- Technical Story: IDEA-004 (устойчивость сетевых операций)

## Context
Сетевые операции (Telegram API и Yandex Disk) периодически падают по временным причинам (таймауты, сетевые ошибки, 5xx, flood control). Голые “3 попытки” без backoff дают лишнюю нагрузку и ухудшают UX.

## Decision
- Для операций `storage.list_dir`, `storage.get_download_url`, `storage.stream_download`, `bot.send_message`, `bot.send_document` используем общий async-wrapper на базе `tenacity.AsyncRetrying`.
- Стратегия ожидания: экспоненциальный backoff с jitter (`wait_random_exponential`).
- Для Telegram flood control (`TelegramRetryAfter`) уважаем `retry_after` и спим не меньше указанного.

## Consequences
- Меньше ложных “ошибок доставки”, выше шанс успешной отправки без re-enqueue job.
- Временная задержка на отдельных задачах увеличивается, но стабильность растёт.

## Links
- Chatlog: `docs/CHATLOG_RU.md` (2026-02-08 22:15 MSK)
- tenacity: https://tenacity.readthedocs.io/
- Telegram Bot API: https://core.telegram.org/bots/api
