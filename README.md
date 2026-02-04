# Adaspeas MVP (Bot + Worker)

Минимальный репозиторий: Telegram bot + worker с автодеплоем на VPS.

Документация (один вход):
- `docs/INDEX_RU.md` — **прочитать в новом чате/ИИ** (карта + правила)
- `docs/WORKFLOW_CONTRACT_RU.md` — правила работы в чате и формат результата
- Остальное: PRD/TECH/OPS по ссылкам из INDEX

## Локальный запуск

```bash
cp .env.example .env
docker compose up --build
```

## Smoke checks (локально)
- Bot health: http://localhost:8080/health
- Bot metrics: http://localhost:8080/metrics
- Worker health: http://localhost:8081/health
- Worker metrics: http://localhost:8081/metrics

## Production “норма”
- `/health` → 200 `{"ok": true}`
- `/metrics` → 401 без логина (Basic Auth через Caddy)
- `/` → 302 на `/health` (Caddy)
