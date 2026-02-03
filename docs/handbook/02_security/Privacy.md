---
doc_id: DOC-PRIVACY
title: Privacy & Data Handling
project: Adaspeas Docs
owner: TBD
status: DONE
version: v1
last_updated: '2026-02-03'
purpose: Правила обработки персональных данных и логирования для Adaspeas Docs.
inputs:
- 01_product/PRD.md
- 02_security/ThreatModelLite.md
outputs:
- Data retention rules
- Log redaction rules
- User data inventory
---

# Privacy & Data Handling

## 1) Что считаем персональными данными (PII)

- Telegram **chat_id/user_id** (идентификаторы).
- Любые свободные текстовые поля, которые может ввести пользователь (поиск).
- Названия файлов могут содержать PII (зависит от содержимого/политики).

## 2) Инвентарь данных, которые храним

| Категория | Где | Зачем | Минимизация |
|---|---|---|---|
| chat_id | SQLite.users | авторизация/доступ | хранить как BIGINT; не логировать |
| роль/статус | SQLite.users | RBAC | enum + timestamps |
| категории/файлы метаданные | SQLite.categories/files | навигация | без “описаний” от пользователей |
| избранное | SQLite.favorites | UX | только связи id |
| audit log | SQLite.audit_log | контроль действий | user_id хранить как hash |

## 3) Логи и редактирование

Требование PRD: **никаких PII в логах**.

Правила:
- `user_id/chat_id` в логах только как `user_hash = sha256(chat_id + salt)`.
- Названия файлов: по умолчанию логировать только `file_id` и размер; имя файла логировать только при debug и с redaction/маскированием.
- Никогда не логировать: OAuth токены, raw YD download URLs, содержимое документов.

## 4) Retention

- Operational logs: 7–14 дней (рекомендуется), затем удаление/ротация.
- Audit log: 90 дней (или по политике заказчика), затем агрегация/очистка.
- Пользовательские данные: хранить пока активен доступ; при удалении пользователя очищать favorites и помечать audit записи как “anonymized”.

## 5) Requests / Compliance

- Админ может выполнить “удаление пользователя” (delete + anonymize audit).
- Инцидент-режим: при подозрении на утечку токена немедленная ротация и отключение выдачи файлов до восстановления.
