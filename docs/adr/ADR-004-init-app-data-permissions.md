# ADR-004: Инициализация прав на /data (SQLite WAL) через init-app-data

Актуально на: 2026-02-07 12:55 MSK

- Status: Accepted
- Date (MSK): 2026-02-07 12:55 MSK
- Deciders: Nikolay, ChatGPT
- Technical Story: инцидент "sqlite3.OperationalError: attempt to write a readonly database" при запуске Compose

## Context
Бот и воркер работают не от root (пользователь `app`, UID/GID по умолчанию 1000). SQLite использует WAL и при старте включает `PRAGMA journal_mode=WAL;`.

При первом запуске (особенно с bind-mount `./data:/data`) Docker может создать директорию `./data` на хосте как `root:root`. В этом случае контейнер под UID/GID приложения не может:
- создавать `*.db-wal`/`*.db-shm` рядом с файлом БД;
- выполнять миграции/инициализацию.

Симптом: падение bot/worker с ошибкой `sqlite3.OperationalError: attempt to write a readonly database`.

Альтернативы:
1) Запускать bot/worker от root (нежелательно).
2) Отключить WAL (теряем преимущества WAL и скрываем инфраструктурную проблему).
3) Всегда чинить права руками на VPS/хосте (ошибки неизбежны).

## Decision
Ввести one-shot сервис `init-app-data`, который монтирует тот же `/data` и выполняет:
- `mkdir -p /data`
- `chown -R <APP_UID>:<APP_GID> /data`

`bot` и `worker` зависят от `init-app-data` через `depends_on: condition: service_completed_successfully`.

Решение применяется и в `docker-compose.prod.yml` (named volume `app_data`), и в `docker-compose.yml` (bind-mount `./data`).

## Consequences
Плюсы:
- устраняется класс "readonly SQLite" без ручных действий;
- сохраняется принцип least-privilege (основные сервисы не root);
- поведение предсказуемо при первом старте и пересоздании контейнеров.

Минусы/риски:
- требуется поддержка `service_completed_successfully` в Docker Compose;
- добавляется одноразовый контейнер в граф зависимостей.

Что нужно сделать:
- обновить OPS runbook и README, чтобы на VPS использовался `docker-compose.prod.yml` (или systemd unit).

## Links
- Chatlog: docs/CHATLOG_RU.md (запись 2026-02-07 12:55 MSK)
- Related ADRs: ADR-003
- Changelog: CHANGELOG.md
