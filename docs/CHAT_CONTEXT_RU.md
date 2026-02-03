# Контекст проекта Adaspeas (бот + автодеплой) — актуально на 2026-02-03 19:50 UTC

Актуально на: 2026-02-03 19:50 UTC

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
  - https://bot.adaspeas.ru/ → 302 на /health (редирект в Caddy)

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
  - docker compose -f docker-compose.prod.yml restart caddy
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

### 6.5 Если / не редиректит на /health
Ожидаемое поведение: `GET /` → 302 Location: /health (делает Caddy).
Если вместо этого 404 от aiohttp, значит Caddy работает со старым конфигом (обычно контейнер не был перезапущен).
Решение:
- на VPS выполнить: `docker compose -f docker-compose.prod.yml restart caddy`
- если это случилось сразу после пуша в main: проверь, что deploy workflow действительно выполнился (и что в нём есть шаг restart caddy).

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

### 9.0 Требования к работе через ChatGPT (чтобы не повторяться)
- В чате **не публикуем команды/код/диффы**. Обсуждаем только план и решения. Реальные изменения передаются **только архивом** по явной команде “собирай архив”.
- Команды для применения архива (распаковка → commit → push) хранятся **в этом репозитории** (см. 9.1), чтобы новый чат не начинался с переписывания инструкций.
- Все правила работы (процесс, стиль, запреты, безопасность, путь к архивам, пуш в main) считаются **истиной из репозитория**. В новом чате первым действием читаем этот файл.

### 9.0.1 Как начать новый чат (копипаст)
Отправь первым сообщением:
- “Прочитай `docs/CHAT_CONTEXT_RU.md` и работаем по нему. Архивы лежат в `/media/nik/0C30B3CF30B3BE50/Загрузки`. Пушим сразу в `main`. В чате код/команды не пишем, только архив по команде.”

### 9.1 Путь к архивам и команда распаковки (Linux Mint)
Архивы, которые готовит ChatGPT, по умолчанию лежат здесь:
- `/media/nik/0C30B3CF30B3BE50/Загрузки`

Применение пакета правок (без `git diff`, пушим сразу в main):
```bash
cd /projects/adaspeas
test -z "$(git status --porcelain)" || { echo "Repo dirty. Commit/stash first."; exit 1; }

tar -xzf "/media/nik/0C30B3CF30B3BE50/Загрузки/<ARCHIVE>.tar.gz" -C /projects/adaspeas

git add -A
git commit -m "<message>"
git push
```

### 9.2 Профиль ассистента (контракт на работу)
Чтобы в новом чате не “настраивать заново”:
- Стиль: кратко, без вывода диффов/кода в чат для внесения правок.
- Режим: пакет правок → проверки/симуляции → архив по команде → ты распаковываешь и пушишь в `main`.
- Ограничения: не плодить файлы в `docs/` без необходимости; все “живые” доки с таймстемпом и таблицей изменений.
- Безопасность: никаких секретов/токенов/паролей в чат и в git.

Локальная среда (операторская):
- ОС: Linux Mint
- Локальный репозиторий: `/projects/adaspeas`

## 11) Чеклист `.env` (обязательно для прода)
Минимальный набор переменных в `/opt/adaspeas/.env` (значения не коммитим):

- `BOT_TOKEN`
- `YANDEX_OAUTH_TOKEN`
- `YANDEX_BASE_PATH` (обычно `/Adaspeas`)
- `SQLITE_PATH` (прод: `/data/app.db`)
- `REDIS_URL` (обычно `redis://redis:6379/0`)
- `ACME_EMAIL`
- `METRICS_USER`
- `METRICS_PASS`
- `IMAGE` (например `ghcr.io/nikmagrus-creator/adaspeas_docs:latest`)

Если меняли `deploy/Caddyfile`, конфиг применится только после рестарта `caddy` (в CI это делается автоматически).

## История изменений
| Дата/время (UTC) | Автор | Тип | Кратко что изменили | Причина/ссылка | Commit/PR |
|---|---|---|---|---|---|
| 2026-02-03 19:35 UTC | Nikolay | ops/doc | Added .env checklist + archive path; aligned SQLITE_PATH/IMAGE | env discipline | |
| 2026-02-03 17:45 UTC | Nikolay | doc/ops | Зафиксирован процесс (архив/пуш по команде), добавлены таймстемпы и “лист изменений” | дисциплина/сейвпоинт | |
| 2026-02-03 18:20 UTC | Nikolay | doc/ops | Выравнены доки с фактическими infra файлами (compose/Caddy/bootstrap), добавлен редирект /→/health | консистентность/ops | |
| 2026-02-03 19:10 UTC | Nikolay | doc/ops | Зафиксирован путь к архивам, убран обязательный git diff, добавлен профиль ассистента и рестарт caddy после деплоя | удобство/воспроизводимость | |
| 2026-02-03 19:20 UTC | Nikolay | ops/doc | Уточнены команды восстановления SQLite (без ловушки с TS), улучшен runbook по редиректу /→/health | удобство/безошибочность | |