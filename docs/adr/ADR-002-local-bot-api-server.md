# ADR-002: Использовать Local Bot API Server для доставки файлов

Актуально на: 2026-02-06 00:10 MSK

- Status: Proposed
- Date (MSK): 2026-02-06 00:10 MSK
- Deciders: TBD
- Technical Story: docs/CHATLOG_RU.md (2026-02-06)

## Context
Adaspeas позиционируется как “закрытая библиотека” (каталог папок/файлов на внешнем хранилище, выдача через Telegram).

Стандартный Telegram Bot API (`https://api.telegram.org`) ограничивает отправку файлов ботом размером до 50 MB, а скачивание файлов с Telegram серверов ботом — до 20 MB. Для библиотеки это почти гарантированно создаёт тупик: достаточно одного PDF/видео/архива...

Telegram предоставляет Local Bot API Server (проект `telegram-bot-api`) с режимом `--local`, который снимает часть лимитов: upload до 2000 MB и скачивание без лимита (практически до 2 GB).

## Decision
Добавить в docker-compose сервис `telegram-bot-api` и переключить bot/worker на него (через `LOCAL_BOT_API_URL`) для всех операций, где возможны файлы > 50 MB.

## Consequences
Плюсы:
- Поддержка “библиотечных” файлов (до 2 GB) без обходных костылей.
- Более быстрые операции с файлами (в т.ч. возможность отправлять по локальному пути).

Минусы/риски:
- Дополнительный сервис на VPS (ресурсы, volume, мониторинг).
- Нужны `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`.

Что нужно сделать:
- Добавить сервис в `docker-compose.prod.yml` (и при необходимости dev compose).
- Обновить конфигурацию aiogram (base URL) в bot/worker.
- Добавить smoke/healthcheck, чтобы CI не ломался.

## Links
- Chatlog: `docs/CHATLOG_RU.md` (2026-02-06 00:10 MSK)
- Related: `docs/TECH_SPEC_RU.md` (разделы 2.1, 6)
