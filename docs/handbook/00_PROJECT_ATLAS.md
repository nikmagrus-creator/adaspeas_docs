---
doc_id: "DOC-ATLAS"
title: "Project Atlas"
project: "Adaspeas Docs"
owner: "TBD"
status: "DONE"
version: "v1"
last_updated: "2026-02-03"
manifest: "00_manifest.yaml"
---

# 00_PROJECT_ATLAS (START HERE)

## 1) Коротко о продукте
Adaspeas Docs: закрытая доставка документов через Telegram. Хранение: Yandex Disk. VPS = прокси/контроллер очередей/безопасность/наблюдаемость.
Ограничения: Local Bot API для файлов > 50MB; лимит файла ≤ 2GB. Доставка: streaming Yandex Disk → Local Bot API → Telegram. Принцип: VPS не хранит файлы постоянно.
SLA: навигация < 500ms, RTO < 1 мин, retry задач ≤ 3.

## 2) Текущая стадия
- Current: **PRD_LOCKED**
- Target next: **ARCHITECTURE_LOCKED**
- Gate status: **BLOCKED**
- Blockers:
  - `02_security/ThreatModelLite.md`
  - `03_arch/ArchitectureSpec.md`
  - `03_arch/ADR/README.md`
  - `03_arch/DataModel.md`
  - `03_arch/StateMachines.md`
  - `04_ops/ObservabilitySpec.md`

## 3) AI Operating Rules (жёстко)
1) Сначала читать `00_manifest.yaml`, затем этот Atlas, затем `01_product/PRD.md`.
2) Нельзя создавать новые файлы вне путей, перечисленных в `00_manifest.yaml`.
3) Если файл существует и указан в manifest, его **только обновлять** (update-first). Дубликаты запрещены.
4) Новый файл разрешён только если в manifest `status: MISSING` и путь уже задан.
5) После любых правок обновлять: manifest (status/last_updated/stage) и этот Atlas (стадия/гейты/карта).
6) Каждый документ обязан иметь YAML header и поля: doc_id, purpose, inputs, outputs, status.
7) Ответ обязан включать **Patch Report** (какие файлы изменены и что сделано).

## 4) Gate Checklist: PRD_LOCKED → ARCHITECTURE_LOCKED
(Считать “DONE” только когда содержимое реально заполнено, а не когда файл создан.)
- [ ] 02_security/ThreatModelLite.md
- [ ] 03_arch/ArchitectureSpec.md
- [ ] 03_arch/ADR/README.md + ключевые ADR
- [ ] 03_arch/DataModel.md
- [ ] 03_arch/StateMachines.md
- [ ] 04_ops/ObservabilitySpec.md
- [ ] (желательно) 04_ops/Runbook.md (черновик)

## 5) Document Map (что и для чего)
- Atlas (DOC-ATLAS): Единая навигация, стадия, чеклисты, правила для ИИ — **DONE** — `00_PROJECT_ATLAS.md`
- Manifest (DOC-MANIFEST): Источник правды по статусам документов и стадии — **DONE** — `00_manifest.yaml`
- Glossary (DOC-GLOSSARY): Словарь терминов — **MISSING** — `00_Glossary.md`
- Changelog (DOC-CHANGELOG): Журнал изменений архива — **DRAFT** — `00_CHANGELOG.md`
- VisionScope (DOC-VISION): Зачем продукт существует, scope и не-цели — **MISSING** — `01_product/VisionScope.md`
- UserFlows (DOC-FLOWS): Сценарии пользователей/админов — **MISSING** — `01_product/UserFlows.md`
- PRD (DOC-PRD): Требования, UX, SLA, ограничения — **DONE** — `01_product/PRD.md`
- ThreatModelLite (DOC-THREAT): Угрозы и меры — **MISSING** — `02_security/ThreatModelLite.md`
- Privacy (DOC-PRIVACY): Политика данных и логов — **MISSING** — `02_security/Privacy.md`
- ArchitectureSpec (DOC-ARCH): Архитектура C4 и потоки — **MISSING** — `03_arch/ArchitectureSpec.md`
- ADR_Index (DOC-ADR-INDEX): Индекс ADR — **MISSING** — `03_arch/ADR/README.md`
- ADR_0001 (ADR-0001): Очередь: источник истины — **MISSING** — `03_arch/ADR/ADR-0001-queue-source-of-truth.md`
- ADR_0002 (ADR-0002): Streaming vs spool — **MISSING** — `03_arch/ADR/ADR-0002-streaming-vs-spool.md`
- ADR_0003 (ADR-0003): Identity model — **MISSING** — `03_arch/ADR/ADR-0003-identity-model.md`
- DataModel (DOC-DATA): Схема данных — **MISSING** — `03_arch/DataModel.md`
- StateMachines (DOC-STATE): Машины состояний — **MISSING** — `03_arch/StateMachines.md`
- InterfaceContracts (DOC-CONTRACTS): Контракты интерфейсов — **MISSING** — `03_arch/InterfaceContracts.md`
- ObservabilitySpec (DOC-OBS): Наблюдаемость — **MISSING** — `04_ops/ObservabilitySpec.md`
- Runbook (DOC-RUNBOOK): Операции и инциденты — **MISSING** — `04_ops/Runbook.md`
- ReleaseUpgradePlan (DOC-RELEASE): Релизы и апгрейды — **MISSING** — `04_ops/ReleaseUpgradePlan.md`
- TestStrategy (DOC-TEST): Стратегия тестов — **MISSING** — `05_quality/TestStrategy.md`
- FailureModes (DOC-FM): Failure modes — **MISSING** — `05_quality/FailureModes.md`
- ImplementationPlan (DOC-PLAN): План реализации — **MISSING** — `06_planning/ImplementationPlan.md`
- Milestones (DOC-MILESTONES): Вехи — **MISSING** — `06_planning/Milestones.md`
- Backlog (DOC-BACKLOG): Бэклог — **MISSING** — `06_planning/Backlog.md`

## 6) Architecture Snapshot
(Заполняется после появления `03_arch/ArchitectureSpec.md`.)

## 7) Open Decisions (в ADR)
- Queue source of truth (SQLite vs Redis)
- Streaming vs temporary spool (если Local Bot API требует filepath)
- Identity model (chat_id, контексты, инвайты)
- Caching & invalidation для SLA

## 8) Next Actions (5)
1) Заполнить Threat Model Lite v1
2) Заполнить Architecture Spec v1
3) Заполнить Data Model + State Machines v1
4) Заполнить Observability Spec v1
5) Обновить manifest: перевести блокеры в DONE и поднять стадию

## 9) Patch Report
- Пока пусто (будет заполняться при изменениях).
