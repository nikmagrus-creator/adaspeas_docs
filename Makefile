.PHONY: env up down up-prod down-prod ps-prod logs-prod test lint smoke fix-data-perms fix-data-perms-prod

env:
	@test -f .env || cp .env.example .env

# Локальный запуск (Linux Mint/Ubuntu):
# - выставляем APP_UID/APP_GID текущего пользователя, чтобы файлы в ./data не становились root:root
# - init-app-data всё равно подстрахует первый запуск (см. docker-compose.yml)
up: env
	APP_UID=$$(id -u) APP_GID=$$(id -g) docker compose up --build

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
	APP_UID=$$(id -u) APP_GID=$$(id -g) docker compose run --rm init-app-data

fix-data-perms-prod: env
	docker compose -f docker-compose.prod.yml run --rm init-app-data

test:
	PYTHONPATH=src python -m pytest -q || test $$? -eq 5

lint:
	python -m compileall -q src

smoke:
	@set -euo pipefail; \
	ENV_FILE_PATH=".env.smoke"; \
	trap 'ENV_FILE="'"$$ENV_FILE_PATH"'" docker compose down --remove-orphans >/dev/null 2>&1 || true; rm -f "'"$$ENV_FILE_PATH"'" >/dev/null 2>&1 || true' EXIT; \
	if [ -f .env.example ]; then cp .env.example "$$ENV_FILE_PATH"; else : > "$$ENV_FILE_PATH"; fi; \
	# Включаем CI_SMOKE=1, чтобы бот не падал на фейковом токене (и /health поднимался). \
	if grep -q "^CI_SMOKE=" "$$ENV_FILE_PATH"; then sed -i "s/^CI_SMOKE=.*/CI_SMOKE=1/" "$$ENV_FILE_PATH"; else echo "CI_SMOKE=1" >> "$$ENV_FILE_PATH"; fi; \
	# Фейковый токен валидного формата (цифры:строка) подходит для smoke-режима. \
	if grep -q "^BOT_TOKEN=" "$$ENV_FILE_PATH"; then sed -i "s/^BOT_TOKEN=.*/BOT_TOKEN=123456789:smoke_token_replace_me/" "$$ENV_FILE_PATH"; else echo "BOT_TOKEN=123456789:smoke_token_replace_me" >> "$$ENV_FILE_PATH"; fi; \
	# В smoke не требуем админов. \
	if grep -q "^ADMIN_USER_IDS=" "$$ENV_FILE_PATH"; then sed -i "s/^ADMIN_USER_IDS=.*/ADMIN_USER_IDS=/" "$$ENV_FILE_PATH"; else echo "ADMIN_USER_IDS=" >> "$$ENV_FILE_PATH"; fi; \
	ENV_FILE="$$ENV_FILE_PATH" docker compose up -d --build; \
	python - <<'PY'\
import time, urllib.request\
\
def wait(url, timeout=90):\
    deadline = time.time() + timeout\
    last = None\
    while time.time() < deadline:\
        try:\
            with urllib.request.urlopen(url, timeout=2) as r:\
                if 200 <= r.status < 300:\
                    return True\
        except Exception as e:\
            last = e\
        time.sleep(1)\
    raise SystemExit(f"timeout waiting for {url}: {last}")\
\
wait("http://localhost:8080/health")\
wait("http://localhost:8081/health")\
print("smoke ok")\
PY
