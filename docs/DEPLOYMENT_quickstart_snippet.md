## Быстрый старт на новом VPS (bootstrap)

На VPS (под пользователем с доступом к docker):

1) Клонировать и поднять базу:
REPO_URL=git@github.com:nikmagrus-creator/adaspeas_docs.git \
APP_DIR=/opt/adaspeas \
BRANCH=main \
./deploy/bootstrap_vps.sh

Если репозиторий/образы приватные, передай GHCR токен (pull):
REPO_URL=git@github.com:nikmagrus-creator/adaspeas_docs.git \
APP_DIR=/opt/adaspeas \
BRANCH=main \
GHCR_USER=nikmagrus-creator \
GHCR_PAT=<token> \
./deploy/bootstrap_vps.sh

2) Заполнить /opt/adaspeas/.env (BOT_TOKEN, ADMIN_USER_IDS, ACME_EMAIL, METRICS_* и т.д.)
3) Открыть порты 80/443 и настроить DNS bot.adaspeas.ru → IP VPS
4) Проверка:
- systemctl status adaspeas-bot
- curl https://bot.adaspeas.ru/health
