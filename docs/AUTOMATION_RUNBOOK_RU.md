# Автоматический режим разработки и выката (GitHub → VPS)

Цель: один раз настроить инфраструктуру, после чего любой push в `main` автоматически:
1) собирает Docker image,
2) публикует его в GHCR,
3) обновляет прод на VPS (pull + restart).

## Источник истины
- Код и конфиги живут в Git.
- На VPS ничего “не правим руками”. Если хочется “быстро поправить”, это почти всегда дорога в ад при следующем деплое.

## Как это работает
- GitHub Actions: `.github/workflows/deploy.yml`
  - Build + push: `ghcr.io/<owner>/<repo>:latest` и `:SHA`
  - Deploy: SSH на VPS и `docker compose pull && docker compose up -d`

- Прод-стек: `docker-compose.prod.yml`
  - `bot`, `worker` используют один и тот же image (`${IMAGE}`)
  - данные SQLite лежат в volume `app_data` (`/data/app.db`)
  - Caddy обслуживает `https://bot.adaspeas.ru`

## Что считается “готовым к автодеплою”
Обязательный минимум:
- проект собирается в Docker без интерактива
- есть `/health` для простого healthcheck
- секреты не лежат в репозитории (только `.env` на VPS и GitHub Secrets)

## Разовый bootstrap на VPS (один раз на новый сервер)
1) На VPS есть Docker.
2) Выполнить:
```bash
REPO_URL=git@github.com:OWNER/REPO.git APP_DIR=/opt/adaspeas BRANCH=main ./deploy/bootstrap_vps.sh
```
3) Заполнить `/opt/adaspeas/.env` по образцу `.env.example`.
4) DNS: `bot.adaspeas.ru` → IP VPS, порты 80/443 открыты.

## GitHub Secrets (Repository → Settings → Secrets and variables → Actions)
Обязательные:
- `VPS_HOST` – публичный IP/host VPS
- `VPS_USER` – пользователь для SSH (лучше отдельный)
- `VPS_SSH_KEY` – приватный ключ (без пароля), который есть в `~/.ssh/authorized_keys` на VPS
- `VPS_PORT` – обычно 22
- `APP_DIR` – обычно `/opt/adaspeas`

Если репозиторий private (или нужна авторизация на pull образов):
- `GHCR_USER` – логин GitHub
- `GHCR_PAT` – Personal Access Token с `read:packages`

## Быстрые команды на VPS (оператору)
Статус:
```bash
systemctl status adaspeas-bot
docker compose -f /opt/adaspeas/docker-compose.prod.yml ps
```

Логи:
```bash
cd /opt/adaspeas
docker compose -f docker-compose.prod.yml logs -f --tail=200 bot
docker compose -f docker-compose.prod.yml logs -f --tail=200 worker
docker compose -f docker-compose.prod.yml logs -f --tail=200 caddy
```

Ручной деплой (если GitHub временно сломан):
```bash
cd /opt/adaspeas
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

## Роллбек
У нас теги:
- `:latest`
- `:<git-sha>`

Чтобы откатиться на конкретный SHA:
1) В `.env` (или прямо в shell) выставить IMAGE:
```bash
export IMAGE=ghcr.io/OWNER/REPO:<git-sha>
```
2) Перезапустить:
```bash
cd /opt/adaspeas
docker compose -f docker-compose.prod.yml up -d
```

## Где хранить “память проекта”
- Этот файл: `docs/AUTOMATION_RUNBOOK_RU.md`
- Миграции и перенос: `docs/MIGRATION_RUNBOOK_RU.md`
- Развёртывание: `docs/DEPLOYMENT.md`

