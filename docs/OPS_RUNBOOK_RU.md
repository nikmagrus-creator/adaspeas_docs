# OPS_RUNBOOK (RU): деплой, эксплуатация, перенос, инциденты

Актуально на: 2026-02-04 17:30 MSK
Связанные документы:
- Вход: `docs/INDEX_RU.md`
- Правила работы в чате: `docs/WORKFLOW_CONTRACT_RU.md`
- Контракты системы: `docs/TECH_SPEC_RU.md`

## 0) 90 секунд: диагностика и быстрый откат
1) Проверить “норму”:
- `/health` → 200 `{"ok": true}`
- `/metrics` → 401 без auth (prod), доступен с auth
- `/` → 302 на `/health`

2) На VPS:
- `docker ps`
- `docker logs <bot|worker> --tail=200`
- `docker compose pull && docker compose up -d`

3) Rollback: откатить образ/версию (см. раздел Rollback).

## 1) Продовая схема
- Ручные изменения на VPS запрещены: всё через репозиторий и CI/CD.
- VPS директория: `/opt/adaspeas`
- Сервисы: bot, worker, redis, caddy
- Volumes: `app_data`, `caddy_data`, `caddy_config` (если используются)

## 2) Автодеплой
Push в `main` запускает CI/CD:
- build → push в GHCR
- deploy на VPS по SSH
- на VPS: `git fetch` → `git reset --hard origin/main` → `git clean -fd`
- `docker compose pull` → `docker compose up -d`
- перезапуск прокси при необходимости

## 3) Секреты
- На VPS: `/opt/adaspeas/.env`
- В GitHub Secrets: SSH, токены/ключи CI, пароль Basic Auth (если хранится там)

## 4) Перенос на новый VPS (TL;DR)
1) Поднять новый VPS, поставить Docker/Compose.
2) Скопировать `.env`.
3) Перенести volume `app_data` (обязательно), `caddy_*` (желательно).
4) `git clone`/`git fetch` repo → `docker compose up -d`.
5) Проверить `/health`, потом переключать DNS.

## 5) Rollback
- Откатить на предыдущий SHA/тег образа.
- Проверить `/health` и логи.

## 6) Инциденты и постмортем
Если был заметный инцидент:
- зафиксировать Impact, Timeline, Root causes, Actions
- без поиска “виноватого”: фокус на системе и процессах

## История изменений
| Дата/время (UTC) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-04 15:00 MSK | ChatGPT | doc | Добавлен “90 секунд”, TL;DR перенос, ссылка на CONTRACT/INDEX | |
| 2026-02-04 17:30 MSK | ChatGPT | doc | Уточнён запрет ручных правок на VPS и каноничная схема обновлений | |