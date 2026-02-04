# Handoff: Adaspeas MVP (чат от 2026-02-04)

## Контекст и цель
Цель MVP: Telegram-бот показывает структуру папки **/Zkvpr** в Яндекс.Диске (подпапки = категории, файлы = элементы) и по нажатию на файл ставит задачу воркеру на скачивание/отправку документа в чат.

Этот документ фиксирует, что уже сделано, какие решения приняты, какие проблемы найдены, и что делать дальше при продолжении работы (в новом чате/с новой сессией).

## Source of Truth
1) Документация: репозиторий GitHub `nikmagrus-creator/adaspeas_docs`.
2) Вложения/архивы из чата считать потенциально устаревшими. При любых сомнениях по состоянию кода/конфига требуется актуальный архив из локального репозитория или ссылка на текущий commit.
## Каноничные пути (раз и навсегда)
- Local (Linux Mint): `/home/nik/projects/adaspeas`
- Архивы (скачивание): `/media/nik/0C30B3CF30B3BE50/Загрузки`
- VPS: `/opt/adaspeas`

Правило: VPS обновляется только через репозиторий (CI/CD). Ручные изменения на сервере запрещены.


## Текущее состояние (по итогам чата)

### Инфраструктура
- Deploy через GitHub Actions: на VPS выполняется `git fetch/reset --hard origin/main`, затем `docker compose -f docker-compose.prod.yml pull` и `up -d`.
- Переменные окружения берутся с VPS из **/opt/adaspeas/.env** (секреты не коммитятся).
- Caddy используется для HTTPS и BasicAuth на /metrics.

### Важные фиксы, которые были внесены
1) **Пайплайн деплоя падал** из-за попытки `docker compose pull` образа `adaspeas-app:latest` (которого не существует в реестре). Причина: в `docker-compose.prod.yml` были одновременно `image: adaspeas-app:latest` и `build: .`.
   - Исправлено: `docker-compose.prod.yml` переведён на `image: ${IMAGE}` и удалён `build` для prod.

2) **Бот падал при старте** (aiogram v3) из-за неправильного формата `set_my_commands`.
   - Требуется: `BotCommand(...)`, а не список кортежей.

3) **Бот падал при старте** из-за `IndentationError` в `src/adaspeas/bot/main.py` (сломанные отступы вокруг DB init).
   - Исправлено: инициализация БД/Redis возвращена внутрь `async def main()`.

4) Гигиена env:
   - `.env` и `.env.*` должны быть в `.gitignore`.
   - `.env.example` в репозитории не содержит секретов и включает полный набор переменных, которые требует deploy workflow.

### Проверенные эндпойнты
- `GET /health` должен возвращать `{"ok": true}` на bot (порт 8080) и worker (порт 8081).
- `GET /metrics` локально доступен; в проде закрыт BasicAuth на уровне Caddy.

## Конфигурация окружения (prod)

### /opt/adaspeas/.env (обязательно на VPS)
Workflow деплоя валится, если отсутствуют/пустые:
- `BOT_TOKEN`
- `YANDEX_OAUTH_TOKEN`
- `SQLITE_PATH` (обычно `/data/app.db`)
- `REDIS_URL` (обычно `redis://redis:6379/0`)
- `ACME_EMAIL`
- `METRICS_USER`
- `METRICS_PASS`
- `IMAGE` (например `ghcr.io/nikmagrus-creator/adaspeas_docs:latest`)

Плюс для функционала каталога:
- `STORAGE_MODE=yandex`
- `YANDEX_BASE_PATH=/Zkvpr`

## Текущая проблема (не закрыта)

### «При нажатии на категорию ничего не происходит»
Симптом: бот выводит категории (inline keyboard), но нажатия по кнопкам не приводят к действию.

Типовые причины:
1) Polling запущен с ограничением `allowed_updates=["message"]` (тогда `callback_query` не приходит).
2) Нет обработчика `@dp.callback_query(...)` под формат `callback_data`.
3) Есть обработчик, но он не делает `await cq.answer()` / не редактирует сообщение.

## Следующие шаги (рекомендованный план)
1) Проверить, что polling получает `callback_query`:
   - В `start_polling` явно указать `allowed_updates=["message","callback_query"]`.
2) Реализовать обработчики callback:
   - `nav|<id>`: открыть подпапку и перерисовать клавиатуру.
   - `file|<id>`: поставить job на скачивание/отправку.
   - Всегда делать `await cq.answer()`.
3) Добавить пагинацию для больших папок (кнопка «Показать ещё»).
4) Привести тексты `/start` и `/help` к текущим командам (включая `/categories`).
5) (Опционально) Добавить кэш каталога в SQLite с TTL, чтобы не долбить API.

## Как продолжать работу в новом чате
1) Сначала читать `docs/WORKFLOW_CONTRACT_RU.md` и этот handoff.
2) Для диагностики начинать с:
   - `docker compose -f docker-compose.prod.yml ps`
   - `docker compose -f docker-compose.prod.yml logs -n 200 bot`
   - `curl -sS http://localhost:8080/health`
3) Для изменений: только локально → commit → push → VPS синхронизация через Actions.
