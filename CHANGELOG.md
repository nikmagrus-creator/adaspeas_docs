# Changelog

Формат: Keep a Changelog. Версионирование: SemVer (0.y.z допускается для ранней стадии).

## [Unreleased]
- feat: уведомления пользователю и админам при финальной ошибке доставки/синка; access-control проверка в callback-ах
- docs: усилена политика "только main" (шаблон применения паков с optional docker/pytest, инструкция чистки лишних веток origin/локально)
- feat: /search — поиск по каталогу (FTS5 + search_sessions, лимит callback_data 64 байта)
- fix: worker — ретраи/backoff для Telegram/Yandex (tenacity, уважение RetryAfter)

### Added
- feat: /users — админ-список пользователей с поиском/страницами и токен-сессиями (schema v10: admin_sessions)
- feat: аудит скачиваний (таблица download_audit) + админ-команды /audit и /stats
- ops: скрипт deploy/backup_db.py и конкретизированы команды бэкапов в OPS_RUNBOOK_RU.md
- docs: CHATLOG_RU.md (журнал итогов сессий, память чатов)
- docs: ADR-003 (фиксация изменений/идей/решений через CHANGELOG/CHATLOG/ROADMAP/ADR)
- feat: пагинация каталога в `/categories` (настройка `CATALOG_PAGE_SIZE`)
- feat: периодический scheduler синхронизации каталога в worker (настройка `CATALOG_SYNC_INTERVAL_SEC`)
- feat: soft-delete каталога в SQLite (schema v5: `seen_at`, `is_deleted`, meta `catalog_last_sync_deleted`)
### Changed
- ci: отключён Dependabot (убран .github/dependabot.yml, чтобы не создавались ветки)
- docs: закреплён обязательный формат PRE-FLIGHT (что подключить/загрузить перед задачей)
- ops: добавлена секция метрик (/metrics) и требование hashed METRICS_PASS (caddy hash-password)
- docs: убраны упоминания фиктивного админ‑чат/топик (заменено на админ‑чат/топик через ADR)
- ci: deploy требует LOCAL_BOT_API_BASE при USE_LOCAL_BOT_API=1
- ci: удалён PR template (репозиторий без PR/веток)
- docs: переписан WORKFLOW_CONTRACT_RU.md под автономную разработку ассистентом (CHATLOG/ADR/CHANGELOG, инкрементальные пакеты, требования к командам)
- docs: INDEX_RU.md дополнен ссылкой на CHATLOG
- docs: ADR template уточнён (MSK/Status/Consequences)
- ci: docs policy check разрешает docs/CHATLOG_RU.md
- fix: унифицирован fallback порт Local Bot API (8081) в bot/worker
- ci: deploy поднимает Compose profile localbotapi по USE_LOCAL_BOT_API и валидирует TELEGRAM_API_ID/HASH
- ci: деплой на VPS поднимает prod compose с `--remove-orphans` (чтобы не копились orphan контейнеры)
- ci: guard: изменения кода/инфры требуют обновления CHANGELOG или CHATLOG
- docs: синхронизированы env-имена и добавлены истории изменений в живые документы (CONTRACT/TECH/OPS/ROADMAP)
- ops: Makefile: локальный `make up` выставляет UID/GID текущего пользователя; добавлены `make fix-data-perms*` для ручного запуска init-app-data
- docs: README/TECH/OPS дополнены контрактом `/data` (SQLite WAL) и аварийной процедурой восстановления прав
- docs: .env.example дополнен `APP_UID/APP_GID` для prod compose (по умолчанию 1000:1000)

### Fixed
- ops: init-app-data сделан one-shot и bot/worker ждут его завершения (исключены падения SQLite WAL из-за прав на /data)
- ops: в docker-compose.yml добавлен init-app-data для первого запуска (Docker может создать ./data как root:root)
- docs: уточнены правила запуска на VPS (использовать docker-compose.prod.yml / systemd unit)
- fix: /categories — реально применена настройка CATALOG_PAGE_SIZE и добавлены кнопки страниц (callback_data: nav:<id>:<offset>)
- fix: bot: устранён NameError при завершении (storage не определён)
- fix: worker: periodic sync больше не падает на JOB_ENQUEUE_TOTAL
- fix: prod compose healthcheck без переносов строк; caddy не блокирует деплой ожиданием bot healthy
- fix: worker: notify_user принимает settings (устранён NameError)
- chore: удалены артефакты __pycache__/, *.pyc и .pytest_cache/ (не должны попадать в репо/архивы)
