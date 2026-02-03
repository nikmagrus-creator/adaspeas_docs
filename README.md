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

## Production deploy

See `docs/DEPLOYMENT.md`.

## Документация

Смотри `docs/README.md` (единая точка входа, без зоопарка файлов).
Сейвпоинт и правила работы: `docs/CHAT_CONTEXT_RU.md`.

CI trigger

deploy sync check
