# ADR-002: Использовать Local Bot API Server для доставки файлов

Актуально на: 2026-02-10 11:40 MSK

- Status: Accepted
- Date (MSK): 2026-02-06 12:45 MSK
- Deciders: TBD
- Technical Story: docs/CHATLOG_RU.md (2026-02-06)

## Context
Adaspeas позиционируется как “закрытая библиотека” (каталог папок/файлов на внешнем хранилище, выдача через Telegram).

Стандартный Telegram Bot API (`https://api.telegram.org`) ограничивает отправку файлов ботом размером до 50 MB, а скачивание файлов с Telegram серверов ботом — до 20 MB. Для библиотеки это почти гарантированно создаёт тупик: достаточно одного PDF/видео/архива...

Telegram предоставляет Local Bot API Server (проект `telegram-bot-api`) с режимом `--local`, который снимает часть лимитов: upload до 2000 MB и скачивание без лимита (практически до 2 GB).

## Decision
Добавить в Compose сервис `local-bot-api` (профиль `localbotapi`) и переключать bot/worker на него при `USE_LOCAL_BOT_API=1`, используя `LOCAL_BOT_API_BASE` как base URL.

Сервис запускается в режиме `TELEGRAM_LOCAL=1` и требует `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`.

## Consequences
Плюсы:
- Поддержка “библиотечных” файлов (до 2 GB) без обходных костылей.
- Более быстрые операции с файлами (в т.ч. возможность отправлять по локальному пути).

Минусы/риски:
- Дополнительный сервис на VPS (ресурсы, volume, мониторинг).
- Нужны `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`.

Что нужно сделать:
- [x] Добавить сервис в `docker-compose.prod.yml` и `docker-compose.yml` (через profile `localbotapi`).
- [x] Добавить переключатель `USE_LOCAL_BOT_API` + `LOCAL_BOT_API_BASE` в `.env.example`.
- [x] Переключать aiogram (base URL) в bot/worker.
- [x] Поддержать автозапуск профиля `localbotapi` на прод‑деплое (если флаг включён).
- [ ] Добавить e2e проверку на файл > 50 MB (или хотя бы ручной runbook сценарий).

## Links
- Chatlog: `docs/CHATLOG_RU.md` (2026-02-06 00:10 MSK)
- Related: `docs/TECH_SPEC_RU.md` (разделы 2.1, 6)
- Telegram Bot API FAQ: https://core.telegram.org/bots/faq (лимиты 20 MB download / 50 MB upload)
- Telegram Bot API (Sending Files / sendDocument): https://core.telegram.org/bots/api
- tdlib/telegram-bot-api (режим --local, 2000 MB upload): https://github.com/tdlib/telegram-bot-api
