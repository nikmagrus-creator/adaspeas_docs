# TECH_SPEC (RU): архитектура и контракты системы

Актуально на: 2026-02-07 20:10 MSK

Документ описывает целевую архитектуру связки Telegram ↔ VPS ↔ Яндекс.Диск и то, что должно быть истинным (инварианты). Подробные правила процесса см. в `docs/WORKFLOW_CONTRACT_RU.md`, продуктовые цели — в `docs/PRD_RU.md`.


## 0) Карта кода (как сейчас)

- Telegram UI (aiogram): `src/adaspeas/bot/main.py`
- Worker (очередь Redis): `src/adaspeas/worker/main.py`
- Yandex Disk client: `src/adaspeas/storage/yandex_disk.py`
- SQLite schema / DB: `src/adaspeas/common/db.py`
- Config: `src/adaspeas/common/settings.py`
- Docker compose: `docker-compose.yml`, `docker-compose.prod.yml`

### Контракт /data (SQLite WAL) и права

- SQLite работает в WAL режиме и при записи создаёт рядом с БД файлы `*.db-wal`/`*.db-shm`.
- bot/worker запускаются не от root (пользователь приложения).
- Инвариант: каталог `/data` (bind-mount или volume) **должен быть writable** для UID/GID приложения.

Гарантия:
- В обоих compose-файлах есть one-shot сервис `init-app-data`, который перед стартом bot/worker делает `mkdir -p /data && chown -R <UID>:<GID> /data`.
- Для аварийного восстановления см. `docs/OPS_RUNBOOK_RU.md` (раздел про "readonly database") и цели `make fix-data-perms*`.

Важно: карта выше отражает текущую раскладку файлов, но не означает, что реализация уже соответствует PRD. Несоответствия фиксируем в ROADMAP и ADR.


## 1) Компоненты и границы

1) **Telegram клиент (пользователь/админ)** — только интерфейс.
2) **Bot service** — обработка команд/кнопок, проверка доступа, чтение каталога из SQLite.
3) **Worker service** — фоновые задачи (доставка файлов, уведомления, синхронизация).
4) **SQLite** — “кэш‑истина” на VPS: каталог, пользователи, аудит.
5) **Redis** — очередь задач.
6) **Yandex Disk API** — внешний источник структуры папок и файлов.
7) **Local Bot API Server (опционально, но фактически обязателен для “библиотеки”)** — локальный прокси Bot API, снимающий лимиты по размеру файлов.

Инвариант: бот не делает сетевые запросы к Яндекс.Диску “в момент клика пользователя” для построения списка. UI читает из SQLite быстро, синхронизация происходит отдельно.


## 2) Telegram: лимиты и следствия

### 2.1) Размеры файлов

- При работе через стандартный Bot API (`https://api.telegram.org`) бот может загружать файлы до **50 MB**, а скачивать файлы с Telegram серверов до **20 MB**.
- При работе через **Local Bot API Server** (режим `--local`) лимит загрузки повышается до **2000 MB**, а скачивание возможно “без лимита” (практически до тех же 2 GB).

Следствие: для проекта “закрытая библиотека” Local Bot API Server рассматривается как обязательный компонент (см. OPS).

### 2.2) Inline‑кнопки и payload

`callback_data` для inline‑кнопок ограничен **1–64 байта**.
Следствие: нельзя класть в callback реальный путь/имя файла. В callback кладём короткое действие + integer id (например `nav:123`, `dl:456`).


## 3) Данные и модель хранения

Цель БД: быть “быстрым кэшем” и источником для UI, а не зеркалом всех метаданных диска.

### 3.1) Таблица каталога (как сейчас в коде)

`catalog_items` (SQLite, кэш для UI):
- `id` (int, PK)
- `path` (text, UNIQUE) — внутренний путь в хранилище (не показываем пользователю)
- `kind` (folder|file)
- `title` (text) — текст, который показываем в кнопке
- `yandex_id` (text|null) — идентификатор ресурса (в local режиме = path)
- `size_bytes` (int|null)
- `parent_path` (text|null) — указатель на родителя для дерева (см. ADR-006)
- `tg_file_id` / `tg_file_unique_id` (text|null) — кэш Telegram file_id
- `seen_at` (datetime|null) — “последний раз увидели в sync”
- `is_deleted` (0|1) — soft-delete, чтобы не показывать “призраков”
- `updated_at` (datetime)

### 3.2) Пользователи (целевая)

`users`:
- `tg_user_id` (int, PK)
- `status` (guest|pending|active|expired|blocked)
- `access_expires_at` (datetime|null)
- `user_note` (text|null) — то, что заполняет пользователь для идентификации
- `admin_note` (text|null) — заметка админа
- `created_at`, `updated_at`

### 3.3) Аудит

`audit_downloads`:
- `id`
- `ts` (datetime)
- `tg_user_id`
- `catalog_item_id`
- `result` (ok|error)
- `error` (text|null)


## 4) Синхронизация каталога (Disk → SQLite)

Требования:
- UI читает только из SQLite;
- синхронизация запускается админом вручную (`/sync`) и/или автоматически по расписанию внутри `worker` (`CATALOG_SYNC_INTERVAL_SEC>0`);
- синхронизация должна быть безопасной для больших деревьев (лимит `CATALOG_SYNC_MAX_NODES`).

Алгоритм (как реализовано сейчас):
1) Фиксируем `sync_started` как `datetime('now')` из SQLite.
2) Обходим дерево от `YANDEX_BASE_PATH` (или `/` в local) BFS/очередью.
3) Каждый найденный узел апсертим в `catalog_items` и обновляем `seen_at`.
4) После обхода делаем soft-delete: все элементы под корнем, у которых `seen_at` меньше `sync_started` (или NULL), помечаем `is_deleted=1`.
5) Пишем метаданные в `meta`: `catalog_last_sync_at`, `catalog_last_sync_deleted`.

Инварианты:
- синхронизация не блокирует обработку сообщений бота;
- синхронизация должна быть идемпотентна;
- UI всегда может показать “данные устарели, последнее обновление …”.


## 5) Навигация в Telegram (Inline Catalog)

UI строится как дерево:
- “текущая папка” → список папок + список файлов;
- кнопка “Назад”;
- (опционально) кнопка “Обновить каталог” только админам.

Технически:
- callback: `nav:<folder_id>` или `nav:<folder_id>:<page>` — открыть папку (и страницу) внутри inline UI,
- callback: `dl:<file_id>` — запросить скачивание.

Важно:
- Telegram ограничивает `callback_data` у `InlineKeyboardButton` до 64 байт, поэтому в кнопках передаём только короткие идентификаторы (числовой `id` из SQLite), а не пути/URL.
- Для кнопки “Назад” используем `parent_path` из SQLite, без хранения “стека” состояний.
- Для больших папок UI использует пагинацию (`LIMIT/OFFSET`) с размером страницы `CATALOG_PAGE_SIZE`.

Реализация MVP (на сегодня):
- `/sync` (admin) ставит job `sync_catalog` в Redis-очередь; worker рекурсивно обходит хранилище и апсертит дерево в SQLite.
- `nav:<id>` → бот читает детей папки **только** из SQLite (`parent_path=<path>`) и редактирует одно сообщение. В хранилище не ходит.
- `dl:<id>` → бот ставит download-job; worker отправляет файл (через `tg_file_id` fast-path, иначе download+upload).

Инвариант: один экран = одно сообщение, которое редактируется, а не “спамится” в чат.


## 6) Доставка файлов (Disk → VPS → Telegram)

Поток:
1) Пользователь нажимает файл.
2) Bot проверяет доступ и ставит задачу в очередь.
3) Worker обрабатывает задачу:
   - если у файла есть `tg_file_id`: отправляет по `file_id` (быстро, без скачивания с Диска);
   - иначе скачивает файл с Диска во временную директорию и отправляет как новый upload;
   - после успешной отправки сохраняет `tg_file_id`/`tg_file_unique_id` в БД.
4) Пишем запись в `audit_downloads`.

Нюансы:
- При Local Bot API Server можно отправлять файлы локальным путём (`file://...`) без multipart‑upload.
- Если файл слишком большой для текущего режима, задача должна завершаться “внятной” ошибкой в аудит и сообщением админу.


## 7) Уведомления и антифлуд

Уведомления о сроках доступа делаются из worker по расписанию.

Правила:
- предупреждение пользователю и админу за 24 часа до истечения;
- отправка с ограничением скорости (чтобы не получать 429) и с ретраями.


## 8) Конфигурация (env)

Каноничный список переменных см. `.env.example`.

Нормальные значения по умолчанию (dev и prod одинаково):
- `SQLITE_PATH=/data/app.db`
- `LOCAL_STORAGE_ROOT=/data/storage`

Почему так:
- SQLite работает в WAL и создаёт рядом файлы `-wal` и `-shm`, поэтому важна запись именно в каталог с БД.
- `/data` во всех compose монтируется как volume (prod) или bind-mount `./data` (dev), а права под него заранее приводятся one-shot сервисом `init-app-data`.


Минимум для запуска (dev/CI):
- `BOT_TOKEN`
- `ADMIN_USER_IDS` (опционально, CSV)
- `STORAGE_MODE` (`yandex` | `local`)
- `SQLITE_PATH`
- `REDIS_URL`

Опционально (UI/синхронизация каталога):
- `CATALOG_PAGE_SIZE`
- `CATALOG_SYNC_INTERVAL_SEC`
- `CATALOG_SYNC_MAX_NODES`

Если `STORAGE_MODE=yandex`:
- `YANDEX_OAUTH_TOKEN`
- `YANDEX_BASE_PATH` (например `/Zkvpr`)

Если `STORAGE_MODE=local`:
- `LOCAL_STORAGE_ROOT`

Local Bot API Server (опционально, но нужен для файлов > 50 MB):
- `USE_LOCAL_BOT_API=1`
- `LOCAL_BOT_API_BASE` (по умолчанию `http://local-bot-api:8081`)
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (нужны для запуска сервиса `local-bot-api`)

Prod (Caddy/HTTPS/метрики):
- `ACME_EMAIL`, `METRICS_USER`, `METRICS_PASS`, `IMAGE`


## 9) Известные разрывы (gap) относительно текущего кода

- `/categories` показывает inline-навигацию по SQLite (UI не ходит в хранилище).
- Нет модели доступа пользователей (status/expiry) и админ‑инструментов управления доступом.
- Нет админ‑уведомлений об ошибках/истечениях (как минимум: отправка всем `ADMIN_USER_IDS`).
- Нет аудита скачиваний и админ‑статистики.

Закрытие этих разрывов и порядок — в `docs/ROADMAP_RU.md` и ADR.

## История изменений
| Дата/время (MSK) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-07 20:10 MSK | ChatGPT | doc | Пагинация /categories, soft-delete каталога, периодический scheduler sync (env) | |
| 2026-02-07 19:40 MSK | ChatGPT | doc | Синхронизация каталога в фоне: /sync → job_type=sync_catalog, UI DB-only, meta last_sync | |
| 2026-02-06 00:10 MSK | ChatGPT | doc | Зафиксирована базовая архитектура и лимиты Telegram для “библиотеки” | |
| 2026-02-06 12:45 MSK | ChatGPT | doc | Синхронизированы названия env/компонентов с кодом и уточнены текущие gap | |
