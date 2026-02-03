---
doc_id: DOC-BACKLOG
title: Backlog
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: Список задач (черновой), сгруппированный по темам.
inputs:
- 01_product/PRD.md
outputs:
- Prioritized backlog
---

# Backlog (high-level)

P0 (blocking MVP)
- RBAC: user/admin checks + invite flow
- Categories/files CRUD + pagination + breadcrumb
- Redis cache + invalidation on admin changes
- Jobs enqueue/worker + retries + idempotency
- YD OAuth refresh + error mapping
- Telegram delivery via Local Bot API + progress UI
- /status admin-only + core metrics
- Log redaction + “no PII” enforcement tests

P1
- Favorites UX polishing
- Audit log viewer for admins
- Rate limiting per user + global

P2
- Temporary spool fallback + GC + alerts
- Better search ranking
- Localization polish
