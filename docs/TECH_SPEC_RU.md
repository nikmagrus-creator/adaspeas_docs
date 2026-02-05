# Техническая спецификация: Adaspeas (консолидировано)

Актуально на: 2026-02-04 21:00 MSK
Цель: один источник правды по устройству системы и публичным контрактам. Ops-процедуры — в `docs/OPS_RUNBOOK_RU.md`.

## 1) Компоненты
- `bot` (aiohttp): принимает запросы, создаёт/обновляет job, публикует job_id в очередь.
- `worker`: забирает job_id из очереди, выполняет job, пишет статус/результат.
- `redis`: транспорт очереди/временное состояние.
- `caddy`: TLS + reverse proxy + Basic Auth на `/metrics`.

## 2) Порты и маршрутизация
Внутри docker-сети:
- bot: `8080`
- worker: `8081`
- redis: `6379`

Наружу:
- 80/443 → `caddy`
- `caddy` проксирует запросы к bot (и при необходимости к worker).

## 3) Public contracts (MUST/SHOULD)
Эти контракты считаются “публичными” и не меняются случайно.

HTTP:
- `GET /health` **MUST** возвращать 200 и JSON `{"ok": true}`.
- `GET /metrics` **MUST** быть доступен локально; в проде **SHOULD** быть закрыт Basic Auth на уровне Caddy.
- `GET /` **SHOULD** редиректить на `/health` (Caddy).

Данные:
- SQLite **MUST** быть Source of Truth.
- Продовый путь БД **SHOULD** быть `/data/app.db` (volume `app_data`).
- Redis **MUST NOT** считаться источником истины.

Очередь и обработка:
- Очередь переносит `job_id`, а не “большие payload”.
- Worker **MUST** быть идемпотентным.
- Retry **MUST NOT** превышать 3 попытки.

## 4) Наблюдаемость
- `health` обязателен и максимально простой (для curl).
- `metrics` обязателен для отладки/наблюдения.

## 5) Инварианты
- Секреты только в `.env` на VPS и GitHub Secrets.
- Никаких ручных правок на VPS кроме `.env` (иначе git перестаёт быть источником истины).
- Конфиги деплоя/прокси/compose версионируются в git.


## 6) Карта реализации (Implementation Map)
Эта секция нужна для CI-проверки: если меняется реализация/инфраструктура, обновляйте карту.

- Команды Telegram и маршрутизация:
  - `/start`, `/categories`, `/seed`, `/list`, `/download`: `src/adaspeas/bot/main.py`
  - Inline-навигация по папкам/файлам (callback): `src/adaspeas/bot/*` (handlers/routers, если выделены)
- Yandex Disk (листинг каталога, получение ссылок):
  - Клиент API и `list_dir(path)`/download-link: `src/adaspeas/storage/yandex.py` (или эквивалентный модуль storage)
  - Базовый путь каталога: env `YANDEX_BASE_PATH` (пример: `/Zkvpr`)
- Очередь и жизненный цикл job:
  - Публикация job_id в Redis: `src/adaspeas/*` (bot → redis)
  - Воркеры, статусы, ретраи/идемпотентность: `src/adaspeas/worker/*`
  - Хранилище статусов/каталога: `SQLITE_PATH` (SQLite) + `src/adaspeas/db/*`
- Infra / deploy:
  - Prod compose: `docker-compose.prod.yml`
  - Caddy, Basic Auth на `/metrics`: `Caddyfile`/секция caddy в compose
  - Переменные, обязательные для deploy workflow: `BOT_TOKEN`, `YANDEX_OAUTH_TOKEN`, `SQLITE_PATH`, `REDIS_URL`, `ACME_EMAIL`, `METRICS_USER`, `METRICS_PASS`, `IMAGE`


## История изменений
| Дата/время (UTC) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-04 15:00 MSK | ChatGPT | doc | Выделены публичные контракты в стиле MUST/SHOULD | |
| 2026-02-04 21:00 MSK | ChatGPT | doc | Добавлена карта реализации для CI (Implementation Map) + зафиксированы обязательные env для deploy | |
