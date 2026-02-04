# Ops runbook: Adaspeas (деплой, эксплуатация, миграции)

Актуально на: 2026-02-04 00:00 UTC

Этот файл — “живой” и должен оставаться единственным источником ops-правил (деплой, перенос, секреты, диагностика).
Если правим — обновляем таймстемп и добавляем строку в таблицу изменений.

## 0) Что считается нормой
- Deploy pipeline зелёный: build → GHCR → deploy.
- `GET /health` = 200 и тело `{"ok": true}`.
- `GET /metrics` без логина = 401 (Basic Auth через Caddy).
- `GET /` → 302 на `/health` (делает Caddy).
- VPS рабочая копия репозитория совпадает с `origin/main` (кроме `.env`).
- SQLite (`/data/app.db`) живёт в volume `app_data` и не теряется между рестартами.

## 1) Где что находится
- Прод домен: `bot.adaspeas.ru`
- VPS директория: `/opt/adaspeas`
- Контейнеры: `bot` + `worker` + `redis` + `caddy`
- Volume’ы: `app_data`, `redis_data`, `caddy_data`, `caddy_config`

## 2) Деплой (автоматический)
Цепочка:
Push в `main` → GitHub Actions → сборка image → push в GHCR → SSH на VPS → обновление репо на VPS → `docker compose pull/up` → `restart caddy`.

Ключевой момент (обязателен):
- перед обновлением контейнеров VPS должен быть приведён к `origin/main` через `git fetch` + `reset --hard` + `clean -fd`,
иначе будут “обновили image, но забыли compose/Caddyfile”.

## 3) Секреты и конфиги
### 3.1 На VPS (НЕ в git)
`/opt/adaspeas/.env`:
- `BOT_TOKEN`
- `ADMIN_USER_IDS`
- `YANDEX_OAUTH_TOKEN`
- `YANDEX_BASE_PATH` (обычно `/Adaspeas`)
- `SQLITE_PATH` (прод: `/data/app.db`)
- `REDIS_URL` (обычно `redis://redis:6379/0`)
- `ACME_EMAIL`
- `METRICS_USER`, `METRICS_PASS`
- `IMAGE` (например `ghcr.io/nikmagrus-creator/adaspeas_docs:latest`)

### 3.2 GitHub Secrets (Actions)
Обязательные:
- `VPS_HOST`, `VPS_USER`, `VPS_PORT`
- `VPS_SSH_KEY` (приватный ключ)
- `APP_DIR` (`/opt/adaspeas`)

Если image приватный (VPS должен уметь pull):
- `GHCR_USER`
- `GHCR_PAT` (read:packages)

## 4) Быстрые проверки
На VPS:
- `docker ps`
- `curl -sS https://bot.adaspeas.ru/health`
- `curl -i https://bot.adaspeas.ru/metrics` (ожидаем 401 без auth)

## 5) Типовые поломки
### 5.1 `/` не редиректит на `/health`
Если вместо 302 получаешь 404 от aiohttp, обычно Caddy запущен со старым конфигом.
Решение: перезапустить Caddy контейнер (в CI это делается автоматически).

## 6) Ручной деплой (если Actions временно сломаны)
Смысл: `pull` → `up -d` → `restart caddy`.

## 7) Роллбек
У образов есть теги:
- `:latest`
- `:<git-sha>`

Роллбек делается сменой `IMAGE` на нужный `:<git-sha>` и перезапуском.

## 8) Миграция/перенос на новый VPS
### 8.1 Что переносить
Обязательно:
- `app_data` (SQLite: `/data/app.db`)

Желательно:
- `caddy_data`, `caddy_config` (сертификаты/состояние Caddy)

Опционально:
- `redis_data` (обычно можно не переносить)

### 8.2 Стратегия
1) На старом VPS снять бэкап volume’ов (или хотя бы `app.db`).
2) Поднять новый VPS через bootstrap.
3) Остановить сервис, восстановить volume’ы, запустить.
4) Переключить DNS, проверить `/health`.

## 9) Правила дисциплины (чтобы не было боли)
- На VPS не правим конфиги руками (кроме `.env`). Всё остальное только через git.
- Любое изменение infra файлов (compose/Caddy/bootstrap/workflow) — в репозитории.
- Секреты/токены никогда не вставляются в чат и не попадают в git.

## 10) Правила работы через ChatGPT (архивный процесс)
- В чате не публикуем команды/код/диффы для внесения правок.
- Изменения готовятся пакетом → проверки/симуляции → архив по явной команде.
- Пушим напрямую в `main`, если не оговорено иначе.

Локальная среда:
- Репозиторий: `/home/nik/projects/adaspeas`
- Архивы по умолчанию: `/media/nik/0C30B3CF30B3BE50/Загрузки`

### 10.1 Как начать новый чат (копипаст)
Прочитай `docs/OPS_RUNBOOK_RU.md` и работаем по нему.
Репо: `/home/nik/projects/adaspeas`
Архивы: `/media/nik/0C30B3CF30B3BE50/Загрузки`
Пуш: сразу в `main`
В чате: без кода/команд/диффов, только план и список файлов, архив по команде.

## История изменений
| Дата/время (UTC) | Автор | Тип | Кратко что изменили | Причина/ссылка | Commit/PR |
|---|---|---|---|---|---|
| 2026-02-04 00:00 UTC | ChatGPT | doc/ops | Исправлены локальные пути; добавлен копипаст для старта нового чата | меньше трения при переносе | |
