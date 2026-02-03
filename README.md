# Adaspeas MVP (Bot + Worker)

Минимальный стартовый репозиторий под PRD v6.

Ключевые решения:
- SQLite = Source of Truth (users, roles, catalog, jobs)
- Redis = транспорт очереди (job_id)
- Worker идемпотентен, retry <= 3
- Файлы не хранятся на VPS постоянно

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

## Проверка

- Bot health: http://localhost:8080/health
- Bot metrics: http://localhost:8080/metrics
- Worker health: http://localhost:8081/health
- Worker metrics: http://localhost:8081/metrics


## Production deploy
See `docs/DEPLOYMENT.md`.

## Документация
Смотри `docs/README.md` (единая точка входа, без зоопарка файлов).
