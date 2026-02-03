---
doc_id: DOC-FLOWS
title: User Flows
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: UX-флоу на основе PRD, для разработки и тестов.
inputs:
- 01_product/PRD.md
outputs:
- Mermaid flows
- Acceptance hints
---

# User Flows

## 1) Navigation + search (User)

```mermaid
flowchart TD
  A[/start/] --> B[Главный экран: категории + избранное]
  B -->|tap category| C[Список файлов/подкатегорий]
  C -->|breadcrumb/back| B
  C -->|inline search| S[Результаты поиска]
  S -->|tap item| F[Просмотр файла]
```

Acceptance:
- breadcrumb отражает путь
- назад возвращает в предыдущий список
- поиск не ломает навигацию (есть “очистить”)

## 2) Download (User)

```mermaid
sequenceDiagram
  participant U as User
  participant BOT as Bot
  participant R as Redis
  participant W as Worker
  participant YD as Yandex Disk
  participant LBA as Local Bot API
  U->>BOT: tap "Скачать"
  BOT->>BOT: RBAC + limits + create job in SQLite
  BOT->>R: enqueue(job_id)
  W->>R: claim(job_id)
  W->>YD: download stream
  W->>LBA: send stream to Telegram
  LBA-->>U: file delivered
  W->>BOT: update job DELIVERED
```

## 3) Admin flows

- Управление категориями: create/rename/delete (confirm).
- Управление файлами: upload/delete/rename.
- Пользователи: invite code generation, block/unblock.
- /status: health snapshot.
