# Контекст проекта Adaspeas (бот + автодеплой) — актуально на 2026-02-03 18:20 UTC

Актуально на: 2026-02-03 18:20 UTC

Этот файл — “точка сохранения” для переноса работы в новый чат/новую команду/новый VPS без потери контекста.
Источник истины: репозиторий. Никаких “я правил на сервере руками и забыл”.

## 0) Где что находится

- Репозиторий (private): https://github.com/nikmagrus-creator/adaspeas_docs
- Прод домен: bot.adaspeas.ru
- VPS директория приложения: /opt/adaspeas
- Контейнеры: bot + worker + redis + caddy
- Endpoints:
  - https://bot.adaspeas.ru/health → ожидается HTTP 200 {"ok": true}
  - https://bot.adaspeas.ru/metrics → ожидается HTTP 401 без логина (Basic Auth через Caddy)
  - https://bot.adaspeas.ru/ → 404 допустим (просто нет handler в приложении)

### 0.1) Статус “что считается нормой”
- Deploy pipeline зелёный: build → GHCR → deploy.
- `GET /health` = 200 и тело `{"ok": true}`.
- `GET /metrics` без логина = 401.
- VPS рабочая копия репозитория совпадает с `origin/main` (кроме `.env`).
- База данных SQLite (`/data/app.db`) живёт в volume `app_data` и не теряется между рестартами.

## 1) Архитектура и потоки

### Сервисы
- redis: кэш/очередь/внутренние потребности
- bot: основной Telegram бот (aiohttp)
- worker: фоновые задачи (python -m adaspeas.worker.main)
- caddy: reverse proxy + TLS (Let’s Encrypt) + Basic Auth на /metrics

### Сеть и порты
- наружу проброшены 80/443 на caddy
- внутри:
  - bot слушает 8080 (expose)
  - worker 8081 (expose, обычно без внешнего доступа)
  - redis 6379

### Хранилище
- том app_data: хранит /data/app.db (SQLite) и прочие данные приложения
- том redis_data: /data
- тома caddy_data/caddy_config: сертификаты/конфиг caddy

## 2) Деплой: как это работает

Цель: полный “автоматический режим”.
Push в main → GitHub Actions → сборка Docker image → push в GHCR → SSH на VPS → обновление репо на VPS → docker compose pull/up.

### GitHub Actions
Workflow: .github/workflows/deploy.yml
- job build:
  - checkout
  - build/push в ghcr.io/${github.repository}:latest и :${sha}
- job deploy:
  - SSH на VPS
  - СИНХРОНИЗАЦИЯ РЕПО НА VPS (важно для compose/Caddyfile/docs):
    - git fetch origin
    - git reset --hard origin/main
    - git clean -fd
  - docker login ghcr.io (если заданы GHCR_PAT/GHCR_USER)
  - docker compose pull
  - docker compose up -d
  - docker image prune -f

### Почему синхронизация репо на VPS обязательна
Ранее возникла ситуация: image обновлялся, но файлы docker-compose.prod.yml и deploy/Caddyfile на VPS оставались старые.
Это ломает “всё в одном архиве” и делает перенос на новый сервер болезненным.
Решение: перед деплоем всегда приводить VPS к origin/main через reset/clean.

## 3) Секреты и конфиги (где что хранится)

### На VPS (локально, НЕ в git)
Файл: /opt/adaspeas/.env
Содержит:
- BOT_TOKEN (Telegram)
- ADMIN_USER_IDS
- ACME_EMAIL (для Let’s Encrypt)
- METRICS_USER / METRICS_PASS (Basic Auth на /metrics)
- IMAGE=ghcr.io/nikmagrus-creator/adaspeas_docs:latest
- прочие (например YANDEX_OAUTH_TOKEN, если реально используется)

Важно: токены не должны попадать в git. Только .env.example с плейсхолдерами.

### В GitHub Secrets (Repo → Settings → Secrets and variables → Actions)
Ожидаемые secret keys:
- VPS_HOST
- VPS_USER
- VPS_PORT
- VPS_SSH_KEY (приватный ключ)
- APP_DIR (/opt/adaspeas)
- GHCR_USER
- GHCR_PAT (read:packages; для pull приватного image с VPS)

## 4) Что уже сделано (история этапов, важно для будущих переносов)

1) Подготовлен репозиторий “all-in-one”: код + docs + CI/CD + deploy.
2) Настроен доступ VPS к GitHub по SSH:
   - при попытке clone было: Permission denied (publickey)
   - решение: положить приватный ключ в ~/.ssh и настроить ~/.ssh/config на IdentityFile + IdentitiesOnly.
3) Первый запуск docker compose упёрся в GHCR:
   - ошибка: "unauthorized"
   - решение: docker login ghcr.io на VPS с GHCR_PAT (read:packages).
4) Caddy падал при старте:
   - ошибка: parsing caddyfile tokens for 'email' (по факту переменные env не подставлялись)
   - решение: передать .env в сервис caddy через env_file/environment в docker-compose.prod.yml.
5) Предупреждение Caddy:
   - basicauth deprecated → заменили на basic_auth.
6) Предупреждение Redis:
   - vm.overcommit_memory must be enabled → применили sysctl vm.overcommit_memory=1.
7) Предупреждение QUIC/HTTP3:
   - UDP buffer sizes → применили sysctl net.core rmem/wmem max/default.
8) Проблема “VPS не обновляет compose/Caddyfile”:
   - git на VPS отставал от origin/main из-за локальных правок и отсутствия git pull в деплое.
   - решение: stash/синхронизация вручную один раз + обновление workflow (git fetch/reset/clean).
9) Перевыпуск секретов после случайной публикации:
   - BOT_TOKEN и METRICS_PASS были показаны в чате → перевыпущены и обновлены в .env, контейнеры пересозданы.

## 5) Bootstrap нового VPS (перенос за один заход)

Скрипт: deploy/bootstrap_vps.sh
Назначение:
- проверка docker/compose
- sysctl (redis + udp)
- создание APP_DIR
- clone/update repo
- создание .env из .env.example (если нет)
- (опционально) docker login ghcr.io, если заданы GHCR_USER/GHCR_PAT
- установка systemd unit adaspeas-bot.service и запуск

Ключевая идея: новый VPS поднимается одним скриптом + заполнением .env + настройкой DNS/портов + GitHub Secrets.

## 6) Runbook: быстрые проверки и диагностика

### 6.1 Проверить, что всё живо
На VPS:
- docker ps
- curl -sS https://bot.adaspeas.ru/health
- curl -i https://bot.adaspeas.ru/metrics  (ожидаем 401 без auth)

### 6.2 Если GHCR pull “unauthorized”
Симптомы:
- docker compose pull → unauthorized

Проверки/решение:
- На VPS сделать docker login ghcr.io:
  - GHCR_PAT должен иметь минимум read:packages
- В GitHub Secrets должны быть GHCR_USER/GHCR_PAT
- Если repo/пакет приватный, VPS без логина не скачает image.

### 6.3 Если Caddy рестартится
Проверка:
- docker logs --tail 100 adaspeas-caddy-1

Частые причины:
- env не передан в caddy → ACME_EMAIL пустой → Caddyfile не адаптируется
- синтаксис Caddyfile неверный

Решение:
- убедиться, что в docker-compose.prod.yml у caddy есть env_file и environment с ACME_EMAIL/METRICS_*

### 6.4 Если git pull на VPS не работает
Симптом:
- git pull --ff-only ругается на local changes

Решение:
- сервер не должен быть местом ручных правок
- workflow должен делать:
  - git reset --hard origin/main
  - git clean -fd
- ручной фикс (разово):
  - git stash push -m "...", затем pull/reset

### 6.5 Если / отдает 404
Это нормально, если приложение не реализует root route.
Опционально:
- добавить редирект в Caddy (без захвата всех путей): matcher `@root path /` + `redir @root /health 302`
или
- добавить handler в aiohttp.

## 7) “Смоделированные” сценарии, чтобы новый чат/человек не тратил сутки

### Сценарий A: новый VPS, всё с нуля
1) установить docker + docker compose plugin
2) создать пользователя deploy и дать доступ к docker (или работать под root осознанно)
3) DNS bot.adaspeas.ru → IP VPS, открыть 80/443
4) bootstrap:
   - REPO_URL=... APP_DIR=/opt/adaspeas BRANCH=main ./deploy/bootstrap_vps.sh
   - если приватные образы: добавить GHCR_USER/GHCR_PAT
5) заполнить /opt/adaspeas/.env
6) проверить systemctl status adaspeas-bot, curl /health

### Сценарий B: деплой зелёный, но на VPS старые файлы
Причина:
- deploy job обновляет image, но не обновляет git рабочую копию на сервере

Решение:
- в workflow добавить git fetch/reset/clean (уже сделано)
- контроль: git log -1 origin/main и git log -1 на VPS

### Сценарий C: “не запускается после изменения .env”
Причина:
- контейнеры не подхватили env

Решение:
- docker compose up -d --force-recreate bot worker caddy
- проверить логи

### Сценарий D: случайно засветили токен
Решение:
- Telegram: BotFather → revoke token
- обновить /opt/adaspeas/.env
- force-recreate контейнеров
- заменить METRICS_PASS

## 8) Правила (чтобы снова не было боли)
- Не править конфиги на VPS руками (кроме .env). Всё остальное только через git.
- Любое изменение infra файлов (compose/Caddyfile/bootstrap/workflow) должно быть в репозитории.
- Секреты только в GitHub Secrets и /opt/adaspeas/.env.

## 9) Правила работы (чат → пакет правок → симуляции → архив → пуш)
Цель: не терять контекст между чатами и не разводить ручные правки.

- В чате не публикуем код/диффы для внесения правок. Здесь обсуждаем план, риски и список файлов.
- Изменения готовятся “пакетом” (связанный набор правок), затем прогоняются проверки/симуляции.
- Архив с правками и команда на push выдаются только по явной команде.
- Пушим напрямую в `main` (без веток/PR), если не оговорено иначе.
- Новые документы не плодим: правим существующие (исключения: ADR и новый runbook по правилам `docs/README.md`).
- Формат времени во “живых” доках: `YYYY-MM-DD HH:MM UTC` + таблица `История изменений` внизу.
- Секреты/токены никогда не вставляются в чат и не попадают в git.

Локальная среда (операторская):
- ОС: Linux Mint
- Локальный репозиторий: `/projects/adaspeas`

## 10) Бэкап и восстановление SQLite (минимум)
SQLite = источник истины, значит бэкап это не “потом”.

- Где лежит: volume `app_data`, файл `/data/app.db` внутри тома/контейнеров.
- Перед рискованными изменениями (миграции, крупный деплой) сделать бэкап.
- Восстановление выполняется только после остановки контейнеров, чтобы не получить повреждение от параллельной записи.

(Команды держим в `docs/MIGRATION_RUNBOOK_RU.md` или в ops-разделе handbook, чтобы не раздувать этот файл.)

## История изменений
| Дата/время (UTC) | Автор | Тип | Кратко что изменили | Причина/ссылка | Commit/PR |
|---|---|---|---|---|---|
| 2026-02-03 17:45 UTC | Nikolay | doc/ops | Зафиксирован процесс (архив/пуш по команде), добавлены таймстемпы и “лист изменений” | дисциплина/сейвпоинт | |
| 2026-02-03 18:20 UTC | Nikolay | doc/ops | Выравнены доки с фактическими infra файлами (compose/Caddy/bootstrap), добавлен редирект /→/health | консистентность/ops | |

