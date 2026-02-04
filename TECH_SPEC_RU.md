# TECH_SPEC_RU.md — дополнение (чат 2026-02-04)

## Implementation Map (актуально на 2026-02-04)
- Deploy: GitHub Actions → SSH на VPS → `git reset --hard origin/main` → `docker compose -f docker-compose.prod.yml pull` → `up -d`.
- Prod compose: `bot/worker` должны использовать `image: ${IMAGE}`; не использовать `build:` в prod (иначе `pull` ломается).
- Secrets: `/opt/adaspeas/.env` на VPS (не в git). Workflow требует `BOT_TOKEN, YANDEX_OAUTH_TOKEN, SQLITE_PATH, REDIS_URL, ACME_EMAIL, METRICS_USER, METRICS_PASS, IMAGE`.
- Yandex Disk: `STORAGE_MODE=yandex`, `YANDEX_BASE_PATH=/Zkvpr`, OAuth token (scope `cloud_api:disk.read`).
- Telegram UI commands: aiogram v3 требует `BotCommand(...)` для `set_my_commands`.
- Известная проблема: нажатия по inline-кнопкам не работают → проверить `allowed_updates` и обработчики `callback_query` (+ `cq.answer()`).

## History
- 2026-02-04: зафиксирован handoff и контракт по деплою/compose/env.
