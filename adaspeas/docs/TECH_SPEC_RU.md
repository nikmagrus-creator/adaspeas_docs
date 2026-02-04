# Техническая спецификация: Adaspeas (консолидировано)

Актуально на: 2026-02-04 10:33 UTC

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

## 6) Карта реализации (как сейчас сделано в репозитории)

Цель раздела: чтобы через 3 месяца можно было быстро понять “где что лежит” и “как течёт задача”, не перечитывая весь код.

### 6.1) Структура репозитория (ключевые файлы)
- Bot: `src/adaspeas/bot/main.py` (Telegram polling + HTTP `/health`/`/metrics`, создание job, enqueue в Redis)
- Worker: `src/adaspeas/worker/main.py` (HTTP `/health`/`/metrics`, loop чтения очереди, выполнение job, retry ≤ 3)
- Настройки/ENV: `src/adaspeas/common/settings.py` (BOT_TOKEN, ADMIN_USER_IDS, YANDEX_OAUTH_TOKEN, SQLITE_PATH, REDIS_URL, LOG_LEVEL и т.д.)
- База данных: `src/adaspeas/common/db.py` (schema + операции над jobs/users/catalog)
- Очередь Redis: `src/adaspeas/common/queue.py` (ключ очереди `adaspeas:jobs`, enqueue `RPUSH`, dequeue `BLPOP`)
- Клиент Яндекс.Диска: `src/adaspeas/storage/yandex_disk.py` (API `/resources/download`, затем stream по `href`)
- Локальный запуск: `docker-compose.yml` (bot/worker/redis, порты 8080/8081/6379, `./data:/data`)
- Прод: `docker-compose.prod.yml` + `deploy/Caddyfile` (TLS, Basic Auth на `/metrics`, редирект `/` → `/health`)
- CI/CD: `.github/workflows/deploy.yml` (build → push GHCR → deploy по SSH)
- Bootstrap VPS: `deploy/bootstrap_vps.sh` (подготовка `/opt/adaspeas`, systemd unit)

### 6.2) Потоки (MVP)
1) Пользователь вызывает `/download <id>` в Telegram.
2) Bot:
   - создаёт job в SQLite со state `queued`
   - кладёт `job_id` в Redis очередь `adaspeas:jobs`
3) Worker:
   - забирает `job_id` из Redis (`BLPOP`)
   - переводит job в `running`
   - находит `catalog_item` в SQLite
   - скачивает файл с Яндекс.Диска по `yandex_id` (через получение `href` и streaming download)
   - отправляет файл пользователю через Telegram (`send_document`) из временного файла (без постоянного хранения на VPS)
   - ставит state `succeeded`
4) Ошибки:
   - `attempt` увеличивается, `last_error` сохраняется
   - retry ≤ 3: до 2 повторов job возвращается в `queued` и снова enqueue в Redis, после 3-й ошибки → `failed`

### 6.3) Данные (что реально используется)
- `users`: регистрация пользователя при `/start` (upsert).
- `catalog_items`: минимальный каталог файлов (в MVP создаётся демо-запись через `/seed`).
- `jobs`: очередь и состояние задач (queued/running/succeeded/failed/cancelled), `attempt`, `last_error`.

### 6.4) Правило актуализации (обязательное)
Если меняется реализация или эксплуатация, затрагивающая:
- потоки job (создание/очередь/обработка/статусы/ретраи),
- схему/путь SQLite или формат данных,
- env-переменные,
- продовую схему (compose/caddy/домены/порты),
- CI/CD и деплой-скрипты,
то в этом файле **обязательно**:
- обновить строку `Актуально на: ... UTC`,
- добавить строку в “Историю изменений” (ниже).
Если меняется публичный контракт (раздел 3) или инварианты (раздел 5) — дополнительно обновить `CHANGELOG.md`.

## История изменений
| Дата/время (UTC) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-04 10:33 UTC | ChatGPT | doc | Добавлена «Карта реализации» и правило обязательного обновления при изменениях | |
| 2026-02-04 12:00 UTC | ChatGPT | doc | Выделены публичные контракты в стиле MUST/SHOULD | |
