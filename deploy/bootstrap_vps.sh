#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/adaspeas}"
REPO_URL="${REPO_URL:-}"
BRANCH="${BRANCH:-main}"

if [ -z "$REPO_URL" ]; then
  echo "Set REPO_URL to your git repo url, e.g.:"
  echo "  REPO_URL=git@github.com:OWNER/REPO.git ./deploy/bootstrap_vps.sh"
  exit 2
fi

sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER:$USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  cd "$APP_DIR"
  git fetch --all
  git reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Fill it in before starting."
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed."
  exit 3
fi

# systemd unit to keep stack running
sudo tee /etc/systemd/system/adaspeas-bot.service >/dev/null <<'UNIT'
[Unit]
Description=Adaspeas bot (docker compose)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/adaspeas
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now adaspeas-bot.service

echo "Bootstrapped. Now:"
echo "  1) edit $APP_DIR/.env"
echo "  2) set DNS bot.adaspeas.ru -> this VPS"
echo "  3) open ports 80/443"
echo "  4) systemctl status adaspeas-bot"
