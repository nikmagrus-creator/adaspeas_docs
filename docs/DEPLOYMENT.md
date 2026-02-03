# Production deploy (GitHub Actions -> VPS)

Updated at: 2026-02-03 18:20 UTC

This repo supports fully automated deploy to your VPS on every push to `main`.

Key principle:
- The repository is the source of truth. The VPS must not drift from `origin/main` (except `.env`).

## 1) DNS + firewall
- Point `bot.adaspeas.ru` to your VPS public IP.
- Open TCP ports `80` and `443`.

## 2) Bootstrap VPS (one time)
On the VPS:

```bash
cd /tmp
curl -fsSL https://raw.githubusercontent.com/nikmagrus-creator/adaspeas_docs/main/deploy/bootstrap_vps.sh -o bootstrap_vps.sh
chmod +x bootstrap_vps.sh
REPO_URL=git@github.com:nikmagrus-creator/adaspeas_docs.git APP_DIR=/opt/adaspeas ./bootstrap_vps.sh
```

Then edit `/opt/adaspeas/.env`:
- BOT_TOKEN
- YANDEX_OAUTH_TOKEN
- ADMIN_USER_IDS
- ACME_EMAIL
- METRICS_USER / METRICS_PASS
- IMAGE (ghcr.io/nikmagrus-creator/adaspeas_docs:latest)

## 3) GitHub repo secrets
Add these repository secrets:

- `VPS_HOST` = your VPS IP or hostname
- `VPS_USER` = ssh user (non-root)
- `VPS_SSH_KEY` = private key (PEM) that can ssh into the VPS user
- `VPS_PORT` = 22 (or your custom)
- `APP_DIR` = /opt/adaspeas
- `GHCR_USER` = your GitHub username (or org bot)
- `GHCR_PAT` = GitHub PAT with `read:packages` (and optionally `write:packages`)

Notes:
- The workflow already pushes images using `GITHUB_TOKEN`. The VPS needs `GHCR_PAT` to **pull** private images.
- If your repo is public, you can omit `GHCR_PAT` and `GHCR_USER`.

## 4) Trigger deploy
Push to `main`. Workflow `build-and-deploy` will build image, push to GHCR, then deploy.

## 5) What the deploy workflow does
On every push to `main`, GitHub Actions builds and pushes the image to GHCR, then SSHes into the VPS and executes:

1) Sync the repository working copy (important for `docker-compose.prod.yml`, `Caddyfile`, scripts, docs):
- `git fetch origin`
- `git reset --hard origin/main`
- `git clean -fd`

2) Update containers:
- `docker compose -f docker-compose.prod.yml pull`
- `docker compose -f docker-compose.prod.yml up -d`
- `docker image prune -f`


## 6) Verify
- `https://bot.adaspeas.ru/health`
- `https://bot.adaspeas.ru/metrics` (basic auth from .env)

## Changes
| Date/Time (UTC) | Author | Type | Summary | Reason/Link | Commit/PR |
|---|---|---|---|---|---|
| 2026-02-03 17:45 UTC | Nikolay | doc/ops | Documented mandatory repo sync on VPS and standardized timestamps | align with .github/workflows/deploy.yml | |
| 2026-02-03 18:20 UTC | Nikolay | doc/ops | Replaced placeholders with real repo URLs, clarified principle and numbering | usability/copy-paste | |

