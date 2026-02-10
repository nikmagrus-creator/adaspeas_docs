# ADR-001: CI-smoke не должен зависеть от реального Telegram токена

Актуально на: 2026-02-10 22:20 MSK

- Status: Accepted
- Date (MSK): 2026-02-05 19:57 MSK
- Deciders: Nikolay, ChatGPT
- Technical Story: CI smoke / healthchecks (`make smoke`, `.env.example`, workflow deploy)

## Context
`ci-smoke` запускает `docker compose up` и проверяет `/health` у сервисов.
В smoke/CI секретов нет, поэтому токен Telegram заведомо **невалиден**. Для этого режима у нас есть флаг `CI_SMOKE=1`.

При запуске aiogram пытается вызвать `getMe` и при невалидном токене получает `401 Unauthorized`, после чего процесс бота падает и контейнер уходит в restart-loop. В результате healthcheck по порту не проходит.

## Decision
В режиме smoke/CI бот обязан:
- поднять health endpoint и остаться живым,
- не пытаться “доказывать” валидность токена ценой падения процесса.

Реализация:
- при `CI_SMOKE=1` и `TelegramUnauthorizedError` бот логирует проблему и переходит в бесконечное ожидание (не завершая процесс);
- `.env.example` содержит токен “валидный по формату”, но не реальный секрет (чтобы `.env.example` можно было трекать);
- в smoke‑запуске (например `make smoke`) переменная `CI_SMOKE=1` задаётся явно.

## Consequences
Плюсы:
- smoke становится детерминированным и не зависит от внешних сервисов;
- CI проверяет именно инфраструктурную готовность контейнеров и health‑маршрутов.

Минусы:
- smoke не проверяет реальную авторизацию Telegram (это отдельный тип тестов, требующий secrets).

## Alternatives (rejected)
1) Хранить реальный токен в GitHub Secrets и подмешивать в CI.
   Отклонено: не хотим делать smoke зависимым от внешней сети/секретов и усложнять минимальный “green path”.
2) Полностью отключать запуск бота в CI.
   Отклонено: тогда smoke не проверяет жизнеспособность сервиса.

## Links
- Chatlog: `docs/CHATLOG_RU.md` (записи про CI/SMOKE)
- Related ADRs: ADR-005
- Changelog: `CHANGELOG.md`
