# Adaspeas MVP (Bot + Worker)

Минимальный репозиторий: Telegram bot + worker с автодеплоем на VPS.

Документация (один вход):
- `docs/INDEX_RU.md` — **прочитать в новом чате/ИИ** (карта + правила)
- `docs/WORKFLOW_CONTRACT_RU.md` — правила работы в чате и формат результата
- Остальное: PRD/TECH/OPS по ссылкам из INDEX

## Локальный запуск

```bash
cp .env.example .env
# Для локального end-to-end без Яндекс.Диска:
#   - выставь STORAGE_MODE=local
#   - вызови /seed в боте (создаст /data/storage/demo.pdf)
docker compose up --build
```

## Smoke checks (локально)
- Bot health: http://localhost:8080/health
- Bot metrics: http://localhost:8080/metrics (локально открыто; в проде защищено Basic Auth через Caddy)
- Worker health: http://localhost:8081/health
- Worker metrics: http://localhost:8081/metrics (обычно не публикуем наружу)
- Root redirect: http://localhost:8080/ -> 302 на /health (делает само приложение; в проде дополнительно Caddy)

## Bot команды (MVP)
- `/categories` — синхронизирует верхний уровень каталога в SQLite и показывает первые 50 элементов.
  - обычным пользователям **не показывает** внутренние пути хранилища,
  - админам (из `ADMIN_USER_IDS`) показывает пути для отладки.
- `/list` — показывает первые 50 записей из SQLite (аналогично: пути только админам).
- `/download <id>` — ставит задачу на отправку файла worker-ом.
- `/seed` — (admin) добавить тестовый файл в каталог (локальный режим).

## Production “норма”
- `/health` → 200 `{"ok": true}`
- `/metrics` → 401 без логина (Basic Auth через Caddy)
- `/` → 302 на `/health` (Caddy и/или само приложение)


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

По умолчанию бот работает через облачный Bot API и упирается в лимит загрузки файлов.
Для отправки файлов до 2 ГБ поднимаем локальный Telegram Bot API Server.

Шаги:
- заполни в `.env`: `TELEGRAM_API_ID`, `TELELEGRAM_API_HASH`
- включи: `USE_LOCAL_BOT_API=1`
- запусти compose с профилем: `docker compose --profile localbotapi up --build`
