# ADR-009: Ретраи/backoff для Telegram/Yandex через tenacity

Дата: 2026-02-08

## Контекст
Сетевые операции (Telegram API и Yandex Disk) периодически падают по временным причинам (таймауты, сетевые ошибки, 5xx, flood control). Голые “3 попытки” без backoff дают лишнюю нагрузку и ухудшают UX.

## Решение
- Для операций `storage.list_dir`, `storage.get_download_url`, `storage.stream_download`, `bot.send_message`, `bot.send_document` используем общий async-wrapper на базе `tenacity.AsyncRetrying`.
- Стратегия ожидания: экспоненциальный backoff с jitter (`wait_random_exponential`).
- Для Telegram flood control (`TelegramRetryAfter`) уважаем `retry_after` и спим не меньше указанного.

## Последствия
- Меньше ложных “ошибок доставки”, выше шанс успешной отправки без re-enqueue job.
- Временная задержка на отдельных задачах увеличивается, но стабильность растёт.
- Конфигурация управляется через `NET_RETRY_ATTEMPTS` и `NET_RETRY_MAX_SEC`.
