# Changelog

Формат: Keep a Changelog. Версионирование: SemVer (0.y.z допускается для ранней стадии).

## [Unreleased]
- docs: закреплено правило "одна ветка main" и обновлён шаблон применения pack (pull --ff-only, push origin main)

### Added
- docs: CHATLOG_RU.md (журнал итогов сессий, память чатов)
- docs: ADR-003 (фиксация изменений/идей/решений через CHANGELOG/CHATLOG/ROADMAP/ADR)
### Changed
- docs: закреплён обязательный формат PRE-FLIGHT (что подключить/загрузить перед задачей)
- ops: добавлена секция метрик (/metrics) и требование hashed METRICS_PASS (caddy hash-password)
- docs: убраны упоминания фиктивного админ‑чат/топик (заменено на админ‑чат/топик через ADR)
- ci: deploy требует LOCAL_BOT_API_BASE при USE_LOCAL_BOT_API=1
- ci: PR template обновлён (включён docs/DOCS_RATIONALE_RU.md)
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
