.PHONY: env up down up-prod down-prod ps-prod logs-prod test lint smoke fix-data-perms fix-data-perms-prod

env:
	@test -f .env || cp .env.example .env

# Локальный запуск (Linux Mint/Ubuntu):
# - выставляем UID/GID текущего пользователя, чтобы файлы в ./data не становились root:root
# - init-app-data всё равно подстрахует первый запуск (см. docker-compose.yml)
up: env
	UID=$$(id -u) GID=$$(id -g) docker compose up --build

down:
	docker compose down --remove-orphans

# Прод: запускать ТОЛЬКО через docker-compose.prod.yml (на VPS /opt/adaspeas)
up-prod: env
	docker compose -f docker-compose.prod.yml up -d --remove-orphans

down-prod:
	docker compose -f docker-compose.prod.yml down --remove-orphans

ps-prod:
	docker compose -f docker-compose.prod.yml ps

logs-prod:
	docker compose -f docker-compose.prod.yml logs -f --tail=200

# Аварийные команды: починка прав на /data (SQLite WAL).
# Обычно не нужны, потому что init-app-data one-shot выполняется перед bot/worker.
fix-data-perms: env
	UID=$$(id -u) GID=$$(id -g) docker compose run --rm init-app-data

fix-data-perms-prod: env
	docker compose -f docker-compose.prod.yml run --rm init-app-data

test:
	PYTHONPATH=src python -m pytest -q || test $$? -eq 5

lint:
	python -m compileall -q src

smoke:
	CI_SMOKE=1 BOT_TOKEN=123456789:AABBCCDDEEFFaabbccddeeff1234567890 ADMIN_USER_IDS= docker compose up --build
