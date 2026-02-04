# Adaspeas MVP (Bot + Worker)

Минимальный репозиторий: Telegram bot + worker с автодеплоем на VPS.

Ключевые решения:
- SQLite — Source of Truth (users, roles, catalog, jobs)
- Redis — транспорт очереди (job_id)
- Worker идемпотентен, retry ≤ 3
- Файлы не хранятся на VPS постоянно

Документация (сокращена до 3 файлов):
- Продукт (PRD): `docs/PRD_RU.md`
- Техническая спецификация: `docs/TECH_SPEC_RU.md`
- Эксплуатация/деплой/миграции: `docs/OPS_RUNBOOK_RU.md`

## Запуск (локально)

```bash
cp .env.example .env
docker compose up --build
```

## Проверка (локально)
- Bot health: http://localhost:8080/health
- Bot metrics: http://localhost:8080/metrics
- Worker health: http://localhost:8081/health
- Worker metrics: http://localhost:8081/metrics

## Production “норма”
- https://bot.adaspeas.ru/health → 200 `{"ok": true}`
- https://bot.adaspeas.ru/metrics → 401 без логина (Basic Auth через Caddy)
- https://bot.adaspeas.ru/ → 302 на `/health` (Caddy)
