---
doc_id: DOC-ADR-INDEX
title: ADR Index
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: Индекс архитектурных решений (ADR) и правила их ведения.
inputs:
- 03_arch/ArchitectureSpec.md
outputs:
- Официальный список принятых решений
---

# ADR Index

Правила:
- Каждый ADR имеет уникальный номер и короткое имя.
- Статусы: `PROPOSED` → `ACCEPTED` (или `REJECTED`).
- Любая существенная смена решения = новый ADR, старый помечаем superseded.

## ADR list

| ID | Title | Status | Date | Supersedes |
|---|---|---|---|---|
| ADR-0001 | Queue source of truth: SQLite vs Redis | ACCEPTED | 2026-02-03 | - |
| ADR-0002 | Streaming vs temporary spool for file delivery | ACCEPTED | 2026-02-03 | - |
| ADR-0003 | Identity model: chat_id, contexts, invite flow | ACCEPTED | 2026-02-03 | - |
