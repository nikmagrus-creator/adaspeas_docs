# Adaspeas MVP (Bot + Worker)

Минимальный стартовый репозиторий под PRD v6.

Ключевые решения:
- SQLite = Source of Truth (users, roles, catalog, jobs)
- Redis = транспорт очереди (job_id)
- Worker идемпотентен, retry <= 3
- Файлы не хранятся на VPS постоянно

## Карта проекта (где что находится)

- Единая точка входа по документации: `docs/README.md`
- “Сейвпоинт” контекста/процесса/операционки (то, что копируется в новый чат): `docs/CHAT_CONTEXT_RU.md`
- Автоматический режим (CI/CD, выкаты на VPS): `docs/AUTOMATION_RUNBOOK_RU.md`
- Прод-деплой пошагово: `docs/DEPLOYMENT.md`
- Миграция/перенос на новый VPS: `docs/MIGRATION_RUNBOOK_RU.md`
- Workflow деплоя: `.github/workflows/deploy.yml`
- Прод-compose: `docker-compose.prod.yml`
- Bootstrap VPS: `deploy/bootstrap_vps.sh`
- Caddy конфиг: `deploy/Caddyfile`

## Запуск (локально)

```bash
cp .env.example .env
docker compose up --build
```

## Проверка

Локально (если поднимаешь bot/worker напрямую):
- Bot health: http://localhost:8080/health
- Worker health: http://localhost:8081/health

Прод (через Caddy):
- https://bot.adaspeas.ru/health (200)
- https://bot.adaspeas.ru/metrics (401 без auth)

## Production deploy

Смотри `docs/DEPLOYMENT.md`.

## Документация

Смотри `docs/README.md` (единая точка входа, без зоопарка файлов).
Сейвпоинт и правила работы: `docs/CHAT_CONTEXT_RU.md`.
