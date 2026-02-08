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
	@set -euo pipefail; \
	ENV_FILE=.env.smoke; \
	rm -f $$ENV_FILE; \
	cp .env.example $$ENV_FILE; \
	# включаем smoke-режим (бот не падает на фейковом токене, чтобы /health поднялся) \
	if grep -q '^CI_SMOKE=' $$ENV_FILE; then sed -i 's/^CI_SMOKE=.*/CI_SMOKE=1/' $$ENV_FILE; else echo 'CI_SMOKE=1' >> $$ENV_FILE; fi; \
	# в smoke не ограничиваем админов (иначе /sync не протестировать) \
	if grep -q '^ADMIN_USER_IDS=' $$ENV_FILE; then sed -i 's/^ADMIN_USER_IDS=.*/ADMIN_USER_IDS=/' $$ENV_FILE; else echo 'ADMIN_USER_IDS=' >> $$ENV_FILE; fi; \
	# поднимаем в фоне и ждём /health у bot(8080) и worker(8081) \
	ENV_FILE=$$ENV_FILE docker compose up -d --build; \
	fail=0; \
	for i in $$(seq 1 60); do \
	  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1 && curl -fsS http://127.0.0.1:8081/health >/dev/null 2>&1; then \
	    echo 'OK: /health поднялся'; \
	    break; \
	  fi; \
	  sleep 2; \
	  if [ $$i -eq 60 ]; then fail=1; fi; \
	done; \
	if [ $$fail -ne 0 ]; then \
	  echo 'ERROR: smoke timeout (health не поднялся)'; \
	  docker compose ps || true; \
	  docker compose logs --no-color --tail=200 || true; \
	  ENV_FILE=$$ENV_FILE docker compose down --remove-orphans || true; \
	  rm -f $$ENV_FILE; \
	  exit 1; \
	fi; \
	ENV_FILE=$$ENV_FILE docker compose down --remove-orphans; \
	rm -f $$ENV_FILE
