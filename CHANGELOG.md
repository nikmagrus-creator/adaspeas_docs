# Changelog

Формат: Keep a Changelog. Версионирование: SemVer (0.y.z допускается для ранней стадии).

## [Unreleased]

### Added
- Уведомления пользователю и админам при финальной ошибке доставки/синка; проверки доступа в callback-ах.
- `/search` — поиск по каталогу (FTS5 + search_sessions, лимит callback_data 64 байта).
- Аудит скачиваний (таблица download_audit) + админ-команды `/audit` и `/stats`.
- Скрипт `deploy/backup_db.py` и конкретизированы команды бэкапов в `docs/OPS_RUNBOOK_RU.md`.
- `docs/CHATLOG_RU.md` (журнал итогов сессий, память чатов).
- ADR-003 (фиксация изменений/идей/решений через CHANGELOG/CHATLOG/ROADMAP/ADR).
- Пагинация каталога в `/categories` (настройка `CATALOG_PAGE_SIZE`).
- Периодический scheduler синхронизации каталога в worker (настройка `CATALOG_SYNC_INTERVAL_SEC`).
- Soft-delete каталога в SQLite (schema v5: `seen_at`, `is_deleted`, meta `catalog_last_sync_deleted`).

### Changed
- CI: отключён Dependabot (убран `.github/dependabot.yml`, чтобы не создавались ветки).
- Docs/process: закреплён обязательный формат PRE-FLIGHT (что подключить/загрузить перед задачей).
- Ops: добавлена секция метрик (`/metrics`) и требование hashed `METRICS_PASS` (caddy hash-password).
- Docs: убраны упоминания фиктивного админ‑чат/топик (заменено на админ‑чат/топик через ADR).
- CI: deploy требует `LOCAL_BOT_API_BASE` при `USE_LOCAL_BOT_API=1`.
- CI: удалён PR template (репозиторий без PR/веток).
- Docs/process: переписан `docs/WORKFLOW_CONTRACT_RU.md` под автономную разработку ассистентом (CHATLOG/ADR/CHANGELOG, инкрементальные пакеты, требования к командам).
- Docs: `docs/INDEX_RU.md` дополнен ссылкой на CHATLOG.
- Docs: ADR template уточнён (MSK/Status/Consequences).
- CI: docs policy check разрешает `docs/CHATLOG_RU.md`.
- CI: deploy поднимает Compose profile `localbotapi` по `USE_LOCAL_BOT_API` и валидирует `TELEGRAM_API_ID/HASH`.
- CI: деплой на VPS поднимает prod compose с `--remove-orphans` (чтобы не копились orphan контейнеры).
- CI: guard: изменения кода/инфры требуют обновления CHANGELOG или CHATLOG.
- Docs: синхронизированы env-имена и добавлены истории изменений в живые документы (CONTRACT/TECH/OPS/ROADMAP).
- Ops: Makefile: локальный `make up` выставляет UID/GID текущего пользователя; добавлены `make fix-data-perms*` для ручного запуска init-app-data.
- Docs: README/TECH/OPS дополнены контрактом `/data` (SQLite WAL) и аварийной процедурой восстановления прав.
- Docs: README и `.env.example` уточняют обе стороны лимитов Bot API (upload 50 MB / getFile 20 MB) и когда нужен Local Bot API Server.
- Docs: `.env.example` дополнен `APP_UID/APP_GID` для prod compose (по умолчанию 1000:1000).
- Docs/process: усилена политика "только main" (шаблон применения паков с optional docker/pytest, инструкция чистки лишних веток origin/локально).
- Docs/process: уточнено требование к полному архиву для чата (только tracked-файлы через git archive; архивы с __pycache__/pyc считаются неверным входом).

### Fixed
- Docs/process: PRE-FLIGHT перечисляет полный архив как `.tar.gz` (не `.zip`).
- Docs: `docs/HANDOFF_RU.md` больше не ссылается на несуществующий "megapack"; описан правильный переезд через `deploy/make_ai_archive.sh` и обычные pack.
- Docs: устранена коллизия инструкций по полному архиву для чата (zip→tar.gz, make_ai_archive) и приведён формат ADR (001/005/008/009).
- Docs: гигиена и согласованность (CHATLOG актуальность, OPS лимиты getFile 20MB, перенос штампа в PACK_APPLY_TEMPLATE, ссылки ADR-002).
- Docs: ADR Links приведены к шаблону (Chatlog/Related ADRs/Changelog), ADR-006 дополнен Consequences.
- Миграции SQLite: идемпотентный раннер больше не ломает `CREATE TRIGGER ... BEGIN ... END;` и умеет исполнять несколько операторов в одной строке.
- Worker: ретраи/backoff для Telegram/Yandex (tenacity, уважение RetryAfter), включая send_document (upload и cached file_id) и stream_download.
- Ops: init-app-data сделан one-shot и bot/worker ждут его завершения (исключены падения SQLite WAL из-за прав на /data).
- Ops: в `docker-compose.yml` добавлен init-app-data для первого запуска (Docker может создать `./data` как root:root).
- Docs: уточнены правила запуска на VPS (использовать `docker-compose.prod.yml` / systemd unit).
- `/categories`: реально применена настройка `CATALOG_PAGE_SIZE` и добавлены кнопки страниц (callback_data: `nav:<id>:<offset>`).
- Bot: устранён NameError при завершении (storage не определён).
- Worker: periodic sync больше не падает на `JOB_ENQUEUE_TOTAL`.
- Prod compose: healthcheck без переносов строк; caddy не блокирует деплой ожиданием bot healthy.
- Worker: `notify_user` принимает settings (устранён NameError).
- Repo hygiene: удалены артефакты `__pycache__/`, `*.pyc` и `.pytest_cache/` (не должны попадать в репо/архивы).
- Bot: nav callback корректно парсит `nav:<id>:<offset>` и сохраняет пагинацию.
- Fallback поиска (LIKE) ищет по title и path; добавлен тест без FTS.
- Унифицирован fallback порт Local Bot API (8081) в bot/worker.
- Bot: убран недостижимый фрагмент в проверке доступа (ensure_active).