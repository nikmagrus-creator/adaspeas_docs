# Adaspeas MVP (Bot + Worker)

## Процесс изменений (важно)

- Репозиторий ведём **в одну ветку `main`** (без feature-веток и PR).
- Dependabot не используем (он создаёт ветки).
- Любые изменения применяются через инкрементальные `.tar.gz` пакеты (см. `docs/WORKFLOW_CONTRACT_RU.md` и `docs/PACK_APPLY_TEMPLATE_RU.md`).
- На VPS в `/opt/adaspeas` только `git pull --ff-only` и `make up-prod` (ручные правки запрещены).

Минимальный репозиторий: Telegram bot + worker с автодеплоем на VPS.

Документация (один вход):
- `docs/INDEX_RU.md` — **прочитать в новом чате/ИИ** (карта + правила)
- `docs/WORKFLOW_CONTRACT_RU.md` — правила работы в чате и формат результата
- Остальное: PRD/TECH/OPS по ссылкам из INDEX

## Локальный запуск (Linux Mint)

```bash
make env
# Затем открой .env и задай как минимум BOT_TOKEN (и при необходимости ADMIN_USER_IDS).
# По умолчанию данные пишутся в /data: SQLITE_PATH=/data/app.db, LOCAL_STORAGE_ROOT=/data/storage.

# Для локального end-to-end без Яндекс.Диска:
#   - выставь STORAGE_MODE=local
#   - вызови /seed в боте (создаст /data/storage/demo.pdf)
make up
```

Важно про права на `./data` и SQLite WAL:
- bot/worker работают не от root (UID/GID приложения).
- SQLite включает WAL и пишет рядом с БД файлы `*.db-wal`/`*.db-shm`.
- При первом запуске Docker может создать `./data` как `root:root`, из-за чего будет падение `attempt to write a readonly database`.

Норма: в `docker-compose.yml` есть one-shot сервис `init-app-data`, который перед стартом bot/worker делает `mkdir -p /data && chown -R <UID>:<GID> /data`.

Аварийно (если уже сломалось): `make fix-data-perms` и повторить `make up`.


## Smoke checks (локально)
- Bot health: http://localhost:8080/health
- Bot metrics: http://localhost:8080/metrics
- Worker health: http://localhost:8081/health
- Worker metrics: http://localhost:8081/metrics

## Production “норма”
- `/health` → 200 `{"ok": true}`
- `/metrics` → 401 без логина (Basic Auth через Caddy)
- `/` → 302 на `/health` (Caddy)

## VPS (прод) управление

На VPS в `/opt/adaspeas` используем **только** `docker-compose.prod.yml` (или systemd unit из `deploy/bootstrap_vps.sh`).

Коротко:

```bash
make ps-prod
make logs-prod
make up-prod
```

Если запустить просто `docker compose up` без `-f`, будет использоваться `docker-compose.yml` (локальный dev), что легко приводит к проблемам с правами на `./data` и ошибке SQLite readonly.


## Быстрый старт (локально)

```bash
cd /home/nik/projects/adaspeas
make env
make up
```

Smoke-check:

```bash
curl -sSf http://localhost:8080/health
curl -sSf http://localhost:8080/metrics
```

## Большие файлы (выше 50 МБ)

По умолчанию бот работает через облачный Bot API и упирается в лимиты по размеру файлов.
Для отправки файлов до 2000 MB (≈2 GB) поднимаем локальный Telegram Bot API Server в режиме `--local`.

Шаги:
- заполни в `.env`: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
- включи: `USE_LOCAL_BOT_API=1`
- запусти compose с профилем: `docker compose --profile localbotapi up --build`

Ссылки:
- Telegram Bot API: https://core.telegram.org/bots/api

