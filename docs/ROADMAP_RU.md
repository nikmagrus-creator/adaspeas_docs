# ROADMAP (RU): приоритеты разработки

Актуально на: 2026-02-10 16:10 MSK
Этот документ фиксирует порядок работ. Детали требований см. `docs/PRD_RU.md`, целевую архитектуру — `docs/TECH_SPEC_RU.md`.


## Milestone 1 — Фундамент и UX каталога (приоритет №1)

Цель: бот должен выглядеть как продукт и уметь выдавать файлы “библиотечного” размера.

1) **Inline‑навигация каталога** *(done, MVP)*
- папки и файлы через inline‑кнопки
- редактирование одного сообщения
- кнопка “Назад”
- страницы (пагинация) *(done)*
- (опционально) поиск

2) **Local Bot API Server (режим `--local`)** *(done, infra+код)*
- docker‑сервис `local-bot-api` (Compose profile `localbotapi`)
- переключатель в `.env`: `USE_LOCAL_BOT_API=1` + `LOCAL_BOT_API_BASE`
- на прод‑деплое профиль поднимается автоматически, если флаг включён
- IDEA-008: e2e тест на файл > 50 MB (Local Bot API)

3) **Фоновая синхронизация каталога** *(done)*
- UI читает только SQLite
- синхронизация отдельной задачей в worker: вручную админом через /sync
- (опционально) периодический scheduler внутри worker: `CATALOG_SYNC_INTERVAL_SEC>0`
- soft-delete удалённых элементов: `is_deleted=1` (не показываем “призраков”)
- метка “обновлено …” + “удалено …” в UI

4) **Кэширование Telegram `file_id`** *(done, worker)*
- `tg_file_id`/`tg_file_unique_id` в `catalog_items`
- повторная отправка без скачивания с Диска (fast‑path)

Выходной критерий M1:
- активный пользователь кликает папки/файлы и получает файл в 2–3 клика, включая файлы > 50 MB (через Local Bot API).


## Milestone 2 — Контроль доступа (приоритет №2) *(done)*

Цель: ограниченный доступ без инвайт‑кодов, управляемый админами.

- FSM/статусы пользователей: guest → pending → active → expired/blocked — done
- профиль/поле идентификации от пользователя (`user_note`) — done
- админ‑экран `/users`: список пользователей, срок, продление, блокировка — done
  - UI не превращается в “простыню”: пагинация + поиск (через `admin_sessions`, короткий `callback_data`)
- предупреждение за 24 часа пользователю и админам — done
- (опционально) отдельный админ‑чат/топик под уведомления — done (через `ADMIN_NOTIFY_CHAT_ID`, иначе каждому из `ADMIN_USER_IDS`)
## Milestone 3 — Эксплуатация и прозрачность (приоритет №3)

Цель: чтобы админ понимал, что происходит, и система не “умирала тихо”.

- аудит скачиваний (кто/что/когда/результат) — done (download_audit + /audit)
- статистика для админа (минимум: топ файлов, активные пользователи) — done (/stats)
- нормальные сообщения об ошибках + уведомления админам — done (user+admin notify on final failure)
- бэкапы SQLite (+ volume local-bot-api) — done (runbook + backup script)


## Backlog идей (IDEA-###)

| ID | Кратко | Статус | Где фиксируем | Примечание |
|---|---|---|---|---|
| IDEA-001 | Inline‑навигация каталога | done | Milestone 1 | UX ядро |
| IDEA-002 | Фоновая синхронизация каталога | done | Milestone 1 | /sync + scheduler `CATALOG_SYNC_INTERVAL_SEC` |
| IDEA-003 | Пагинация в каталоге | done | Milestone 1 | `CATALOG_PAGE_SIZE` |
| IDEA-007 | Поиск в каталоге | done | Backlog | /search, FTS5 + search_sessions |
| IDEA-004 | Backoff/ретраи для Telegram/Yandex | done | Backlog | Tenacity, уважение RetryAfter |
| IDEA-005 | Авто‑включение `localbotapi` на прод‑деплое | done | deploy.yml | По флагу USE_LOCAL_BOT_API |
| IDEA-006 | CI guard: изменения кода требуют CHANGELOG/CHATLOG | done | deploy.yml | Чтобы не “забывать” след |
| IDEA-008 | E2E: файл > 50 MB (Local Bot API) | planned | Milestone 1 | Проверка цепочки download→upload |


## История изменений
| Дата/время (MSK) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-10 16:10 MSK | ChatGPT | doc | Убран TODO (заменён на IDEA-008) + обновлена актуальность | |
| 2026-02-09 14:30 MSK | ChatGPT | doc | Milestone 2 переведён в done; обновлены правила переезда/контекста | |
| 2026-02-08 23:45 MSK | ChatGPT | doc | Milestone 3: аудит скачиваний (download_audit), админ /audit и /stats, уведомления при падениях, заготовка бэкапов | |
| 2026-02-07 20:10 MSK | ChatGPT | doc | Milestone 1: добавлены пагинация UI, soft-delete и опциональный scheduler синхронизации | |
| 2026-02-07 19:40 MSK | ChatGPT | doc | Milestone 1: каталогу добавлен фоновой sync (job_type=sync_catalog) и UI читает только SQLite | |
| 2026-02-07 12:00 MSK | ChatGPT | doc | Уточнены формулировки про админ‑оповещения (без фиктивных env) | |
| 2026-02-07 15:30 MSK | ChatGPT | doc | Inline‑навигация каталога переведена в done (MVP), уточнено про lazy-sync папок | |
| 2026-02-06 00:10 MSK | ChatGPT | doc | Зафиксированы milestones и приоритеты MVP | |
| 2026-02-06 12:45 MSK | ChatGPT | doc | Добавлены статусы и backlog IDEA-###, синхронизированы env/infra формулировки | |
