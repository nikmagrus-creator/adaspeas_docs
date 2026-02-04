#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/adaspeas}"
REPO_URL="${REPO_URL:-}"
BRANCH="${BRANCH:-main}"
GHCR_USER="${GHCR_USER:-}"
GHCR_PAT="${GHCR_PAT:-}"

if [ -z "$REPO_URL" ]; then
  echo "Set REPO_URL to your git repo url, e.g.:"
  echo "  REPO_URL=git@github.com:OWNER/REPO.git ./deploy/bootstrap_vps.sh"
  exit 2
fi

# --- checks ---
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed."
  exit 3
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is not available (docker compose)."
  exit 4
fi

# --- sysctl hardening (redis + quic/udp buffers) ---
sudo sysctl -w vm.overcommit_memory=1 >/dev/null
echo "vm.overcommit_memory=1" | sudo tee /etc/sysctl.d/99-redis.conf >/dev/null

sudo sysctl -w net.core.rmem_max=7500000 >/dev/null
sudo sysctl -w net.core.wmem_max=7500000 >/dev/null
sudo sysctl -w net.core.rmem_default=7500000 >/dev/null
sudo sysctl -w net.core.wmem_default=7500000 >/dev/null
cat <<'EOF' | sudo tee /etc/sysctl.d/99-quic-udp-buffers.conf >/dev/null
net.core.rmem_max=7500000
net.core.wmem_max=7500000
net.core.rmem_default=7500000
net.core.wmem_default=7500000
EOF

sudo sysctl --system >/dev/null

# --- app dir + repo ---
sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER:$USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  cd "$APP_DIR"
  git fetch --all
  git reset --hard "origin/$BRANCH"
  git clean -fd
fi

cd "$APP_DIR"

# --- env ---
if [ ! -f ".env" ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created .env from .env.example. Fill it in before starting."
fi

# --- ghcr login (optional, but needed for private images) ---
if [ -n "$GHCR_PAT" ]; then
  echo "$GHCR_PAT" | docker login ghcr.io -u "${GHCR_USER:-$(whoami)}" --password-stdin >/dev/null
  echo "Logged in to ghcr.io"
fi

# --- systemd unit ---
sudo tee /etc/systemd/system/adaspeas-bot.service >/dev/null <<UNIT
[Unit]
Description=Adaspeas bot (docker compose)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now adaspeas-bot.service

echo "Bootstrapped."
echo "Next:"
echo "  1) edit $APP_DIR/.env"
echo "  2) ensure DNS bot.adaspeas.ru -> this VPS"
echo "  3) open ports 80/443"
echo "  4) systemctl status adaspeas-bot"
