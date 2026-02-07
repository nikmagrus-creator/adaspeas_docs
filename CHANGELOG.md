# Changelog

Формат: Keep a Changelog. Версионирование: SemVer (0.y.z допускается для ранней стадии).

## [Unreleased]
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
- ci: guard: изменения кода/инфры требуют обновления CHANGELOG или CHATLOG
- docs: синхронизированы env-имена и добавлены истории изменений в живые документы (CONTRACT/TECH/OPS/ROADMAP)
