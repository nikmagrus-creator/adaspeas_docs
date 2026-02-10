# OPS_RUNBOOK (RU): эксплуатация, инциденты, обслуживание

Актуально на: 2026-02-11 00:20 MSK


## 1) Компоненты в проде

Ожидаемые сервисы:
- bot (aiogram): обрабатывает Telegram апдейты, отдаёт UI.
- worker: выполняет фоновые задачи (доставка файлов, синхронизация, уведомления).
- redis: очередь.
- sqlite (файл): каталог/пользователи/аудит.
- (рекомендуется) local-bot-api: Local Bot API Server в режиме `--local`.

Внешние зависимости:
- Telegram (клиенты, сервера).
- Яндекс.Диск (источник файлов).


## 2) Первые 90 секунд при инциденте

1) Проверить, живы ли контейнеры (`docker compose ps`).
2) Проверить логи bot/worker (ошибки 401/403/429, таймауты, падения).
3) Если массовые 429/таймауты — временно выключить шумные задачи (уведомления/синхронизацию), оставив базовый UI.
4) Если сломалась доставка файлов — фиксировать ошибку в аудит и уведомить админов (как минимум: каждому из `ADMIN_USER_IDS`).

## 2.0) Если сервисы стали unhealthy

На проде liveness `/health` всегда должен отвечать быстро. Дополнительно:
- bot: `/ready` показывает состояние polling и последние ошибки инициализации (DB/Redis/Telegram).
- worker: `/ready` показывает состояние воркера, инициализацию DB/Redis и время последней выполненной задачи.

Если деплой/compose падает на `... bot is unhealthy`:

1) Посмотреть состояние контейнеров:
- `docker compose -f docker-compose.prod.yml ps`

2) Посмотреть логи (хватит 200 строк):
- `docker compose -f docker-compose.prod.yml logs --no-color --tail 200 bot worker`

3) Проверить readiness изнутри VPS:
- `curl -fsS http://127.0.0.1:8080/ready || true`
- `curl -fsS http://127.0.0.1:8081/ready || true`

4) Посмотреть Docker health status точечно:
- `docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $(docker compose -f docker-compose.prod.yml ps -q bot worker)`

Если `/ready` показывает `db=retrying` или `redis=retrying`:
- проверить пути/права на volume (`SQLITE_PATH`, каталог для файла, доступность Redis);
- это не должно убивать процесс, но будет видно как `last_error/last_init_error`.

## 2.1) Управление на VPS (важно)

На VPS в `/opt/adaspeas` **в проде** нужно использовать `docker-compose.prod.yml` (или systemd unit из `deploy/bootstrap_vps.sh`).

Важно по процессу:
- Репозиторий ведём **в одну ветку `main`**. На VPS не делаем `checkout` других веток и не держим “временные” ветки на origin.
- Обновление: `cd /opt/adaspeas && git pull --ff-only && make up-prod`.

Причина: `docker compose up` без `-f` берёт по умолчанию `docker-compose.yml`, а он рассчитан на локальный запуск и bind‑mount `./data:/data`.
Если директории `./data` ещё нет, Docker может создать её как `root:root`, и тогда бот/воркер (которые работают не от root) упрутся в ошибку SQLite "attempt to write a readonly database".

Минимальные команды:
- `make ps-prod` / `make logs-prod` (см. Makefile)
- или напрямую: `docker compose -f docker-compose.prod.yml ps` / `docker compose -f docker-compose.prod.yml logs -f --tail=200`


## 2.1.1) Политика репозитория: строго одна ветка `main`

У нас **не должно существовать никаких веток**, кроме `main` (ни локально, ни на `origin`), включая авто‑ветки вида `dependabot/*`.

Почему: любые ветки ломают договорённость о линейном процессе “пакет → коммит в main → автодеплой”. А Dependabot по определению работает через ветки, поэтому в репозитории **не используется** (файл `.github/dependabot.yml` удалён).

Если на GitHub уже накопились ветки, чистим так (выполнять на локальной машине в репозитории):

```bash
cd /home/nik/projects/adaspeas &&
git fetch origin --prune &&

# показать, что лишнее
git branch -r &&

# удалить всё на origin кроме main
for b in $(git for-each-ref refs/remotes/origin --format='%(refname:strip=3)' | grep -vE '^(main|HEAD)$'); do
  echo "delete origin/$b"
  git push origin ":$b"
done &&

git fetch origin --prune &&

# удалить локальные ветки кроме main
for b in $(git for-each-ref refs/heads --format='%(refname:strip=2)' | grep -vE '^(main)$'); do
  echo "delete local $b"
  git branch -D "$b"
done
```

Удаление удалённой ветки через `git push origin :<branch>` соответствует документации git-push.



## 2.1.2) Если случайно начат cherry-pick/merge и репозиторий “needs merge”

Симптомы:
- `git status` пишет `needs merge`.
- В файлах появились маркеры конфликтов вида `<<< HEAD` / `>>> commit`.
- Скрипт применения паков падает с “Репозиторий не чистый”.

Лечение (обычно достаточно отменить незавершённую операцию и вернуть `main` в чистое состояние):
```bash
cd /home/nik/projects/adaspeas

# 0) посмотреть состояние
git status

# 1) отменить незавершённые операции (если есть)
git cherry-pick --abort 2>/dev/null || true
git merge --abort 2>/dev/null || true

# 2) вернуть main к удалённому состоянию (жёстко)
git checkout main
git fetch origin --prune
git reset --hard origin/main

# 3) (опционально) удалить мусорные неотслеживаемые файлы
# git clean -fd
```

Примечание: если у тебя были важные локальные изменения, сначала сделай `git stash`.

## 2.2) Симптом: "sqlite3.OperationalError: attempt to write a readonly database"

Типовой корень:
- SQLite работает в WAL режиме и должен создавать файлы `*.db-wal` и `*.db-shm` рядом с основной БД.
- Если директория `/data` или файл БД принадлежат root (или смонтированы read-only), контейнер под пользователем приложения (по умолчанию UID/GID 1000) не сможет писать.

Проверка (на VPS, даже под пользователем `deploy` это нормально, если есть доступ к Docker):
```bash
cd /opt/adaspeas
docker compose -f docker-compose.prod.yml run --rm bot sh -lc 'id; echo "SQLITE_PATH=$SQLITE_PATH"; ls -la /data || true'
```

Норма:
- в `docker-compose.prod.yml` и `docker-compose.yml` есть one-shot сервис `init-app-data`, который **перед стартом bot/worker** делает `mkdir -p /data && chown -R <APP_UID>:<APP_GID> /data`.
- поэтому при обычном старте (`make up` / `make up-prod`) этот инцидент не должен повторяться.

Аварийная мера (если нужно поднять прямо сейчас):
1) если в compose уже есть сервис `init-app-data`:
```bash
cd /opt/adaspeas
make fix-data-perms-prod
make up-prod
```

2) если по какой-то причине `init-app-data` отсутствует (устаревший compose), можно разово починить права через bot-контейнер от root:
```bash
cd /opt/adaspeas
docker compose -f docker-compose.prod.yml run --rm --user 0:0 bot sh -lc 'chown -R 1000:1000 /data && chmod -R u+rwX,g+rwX /data'
docker compose -f docker-compose.prod.yml up -d --remove-orphans
```
## 3) Local Bot API Server (local-bot-api)

Зачем нужен:
- стандартный Bot API ограничивает размер файлов: upload (multipart) до 50 MB, скачивание через `getFile` до 20 MB.
- Local Bot API Server в режиме `--local` поднимает upload до 2000 MB и позволяет скачивать файлы без ограничения размера (ограничено ресурсами сервера).

См. первоисточник: https://core.telegram.org/bots/api

Что важно в эксплуатации:
- для запуска нужны `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` (получаются в Telegram).
- сервис должен быть доступен только внутри docker-сети (не выставлять наружу без нужды).
- данные tdlib (сессии/кэш) должны жить в volume, иначе при пересоздании контейнера будут сюрпризы.

Минимальная проверка:
- В `.env` выставлен `USE_LOCAL_BOT_API=1` и корректный `LOCAL_BOT_API_BASE`.
- В Compose включён профиль `localbotapi` (например, `COMPOSE_PROFILES=localbotapi docker compose ... up -d`), и сервис `local-bot-api` запущен.
- bot/worker ходят не на `https://api.telegram.org`, а на `LOCAL_BOT_API_BASE`.
- при проблемах сначала смотреть логи `local-bot-api`.


## 3.1) Метрики (/metrics)

Метрики проксирует Caddy (см. `deploy/Caddyfile`) и защищает Basic Auth.

Важно: Caddy **не принимает plaintext пароли** в конфигурации Basic Auth. В `METRICS_PASS` нужно класть **вывод** команды:

```bash
caddy hash-password --plaintext "<пароль>"
```

Затем:
- `METRICS_USER` = логин,
- `METRICS_PASS` = хэш из `caddy hash-password`.

## 4) Яндекс.Диск

Типичные проблемы:
- 401/403: токен истёк/отозван.
- 429: слишком частые запросы (нужна пауза/бэк‑офф).

Правила:
- синхронизация каталога должна идти в фоне и с ограничением частоты.
- токен хранить только в env (`YANDEX_OAUTH_TOKEN`), не в git.
- `YANDEX_BASE_PATH` хранить в env и держать стабильным, иначе “переедут” пути каталога.


## 5) Очереди и антифлуд

Симптомы:
- 429 Too Many Requests от Telegram.

Действия:
- снизить скорость рассылок (уведомления),
- включить очередь/троттлинг,
- для “массовых уведомлений” отправлять порциями.


## 6) Бэкапы

Минимум:
- SQLite файл (каталог/пользователи/аудит).
- (если используется) volume local-bot-api (tdlib data).

Периодичность зависит от критичности, но хотя бы раз в сутки.

SQLite (внутри контейнеров):
- Проверить путь (по умолчанию `SQLITE_PATH=/data/app.db`).
- Сделать бэкап в `/data/backups/` (тот же volume `app_data`):
  - `docker compose exec worker python deploy/backup_db.py --src /data/app.db --dir /data/backups --keep 7`

Local Bot API данные:
- Dev (bind-mount): архивировать `./data/telegram-bot-api/`.
- Prod (named volume `tg_api_data`): экспортировать volume в tar.gz (пример):
  - `docker run --rm -v tg_api_data:/v -v "$PWD"/backups:/out alpine sh -lc "cd /v && tar -czf /out/tg_api_data_$(date +%F).tar.gz ."`


## 7) Админ‑оповещения

Политика уведомлений:
- `ADMIN_USER_IDS` (CSV) задаёт список админов.
- (опционально) `ADMIN_NOTIFY_CHAT_ID` задаёт отдельный чат/топик, куда слать уведомления (если 0/пусто, шлём каждому админу из `ADMIN_USER_IDS`).

Сейчас уведомляем админов о:
- финальных ошибках доставки файлов (после всех ретраев),
- финальных ошибках `sync_catalog`,
- предупреждениях об истечении доступа (если включён access control).

## 8) Признаки деградации и что логировать

Логируем (внутри контейнеров и в БД в виде аудита):
- каждую попытку скачивания (ok/error + причина),
- время синхронизации каталога и число элементов,
- ошибки внешних API (Telegram/Yandex).

Это помогает отвечать на главный вопрос эксплуатации: “что сломалось и у кого”.


## История изменений
| Дата/время (MSK) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-11 00:20 MSK | ChatGPT | ops | Синхронизированы `APP_UID/APP_GID` в dev compose/Makefile и упоминания в runbook (вместо `UID/GID`) | |
| 2026-02-10 19:15 MSK | ChatGPT | ops | Уточнены формулировки лимитов стандартного Bot API (getFile 20MB) и обновлён штамп актуальности | |
| 2026-02-10 18:45 MSK | ChatGPT | ops | Уточнены лимиты стандартного Bot API vs Local Bot API Server (upload 50MB/2000MB, download без лимита) + добавлен первоисточник | |
| 2026-02-08 23:45 MSK | ChatGPT | ops | Milestone 3: конкретизированы бэкапы (скрипт + команды) и актуализированы админ-оповещения (`ADMIN_NOTIFY_CHAT_ID`) | |
| 2026-02-07 14:02 MSK | ChatGPT | ops | Добавлена процедура чистки веток (только main) и запрет Dependabot как источника веток | |
| 2026-02-07 12:00 MSK | ChatGPT | doc | Уточнены админ‑оповещения и добавлена секция метрик (/metrics) с требованием hash-password | |
| 2026-02-07 12:55 MSK | ChatGPT | ops | Уточнено управление на VPS (prod compose) и добавлен runbook для readonly SQLite + init-app-data | |
| 2026-02-06 00:10 MSK | ChatGPT | doc | Зафиксированы операции/инциденты и необходимость Local Bot API | |
| 2026-02-06 12:45 MSK | ChatGPT | doc | Синхронизированы env/Compose profiles и уточнены правила админ‑уведомлений | |
