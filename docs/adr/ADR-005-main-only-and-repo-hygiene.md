# ADR-005: Репозиторий только с веткой main + гигиена env

Актуально на: 2026-02-10 20:45 MSK

- Status: Accepted
- Date (MSK): 2026-02-07 12:30 MSK
- Deciders: Nikolay, ChatGPT
- Technical Story: docs/WORKFLOW_CONTRACT_RU.md (правила процесса) / docs/CHATLOG_RU.md (2026-02-07)

## Context
Мы ведём этот репозиторий как «документационный монорельс»: одна ветка `main`, без PR/merge/cherry-pick/rebase.

Причины:
- минимизировать конфликты в Markdown (особенно в `docs/CHATLOG_RU.md` и операционных файлах);
- упростить деплой (на VPS делаем `git pull --ff-only` и без «историй из PR»);
- не тратить время на поддержку зависимых бранчей (dependabot) и шаблонов PR.

Параллельно нужен жёсткий контроль секретов:
- файлы `.env*` не должны попадать в git,
- единственное исключение: `.env.example` как безопасный шаблон.

## Decision
1) Политика веток:
- `main` единственная «живая» ветка.
- Любые появившиеся ветки (включая dependabot) удаляются.
- В repo удалены `.github/dependabot.yml` и PR template, чтобы не провоцировать PR-процессы.

2) Гигиена env:
- `.env` и любые `.env.*` игнорируются через `.gitignore`.
- `.env.example` обязателен в репозитории (шаблон без секретов).
- CI проверяет: `.env.example` трекается, а любые другие `.env*` в индексе запрещены.

## Consequences
Плюсы:
- меньше конфликтов, быстрее обновления, проще поддержка;
- на VPS деплой детерминированный (fast-forward);
- снижен риск утечки секретов.

Минусы:
- обновления зависимостей (как зависимые ветки) не приходят автоматически;
- если кто-то всё же начинает cherry-pick/merge/rebase, придётся руками разруливать конфликты.

## Links
- Chatlog: docs/CHATLOG_RU.md (2026-02-07: правила main-only + repo hygiene)
- Related ADRs: ADR-001
- Related: docs/OPS_RUNBOOK_RU.md (чистка лишних веток) / docs/WORKFLOW_CONTRACT_RU.md
- Changelog: CHANGELOG.md
