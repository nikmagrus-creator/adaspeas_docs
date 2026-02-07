.PHONY: env up down up-prod down-prod ps-prod logs-prod test lint smoke

env:
	@test -f .env || cp .env.example .env

up: env
	docker compose up --build

down:
	docker compose down

up-prod: env
	docker compose -f docker-compose.prod.yml up -d

down-prod:
	docker compose -f docker-compose.prod.yml down --remove-orphans

ps-prod:
	docker compose -f docker-compose.prod.yml ps

logs-prod:
	docker compose -f docker-compose.prod.yml logs -f --tail=200

test:
	PYTHONPATH=src python -m pytest -q || test $$? -eq 5

lint:
	python -m compileall -q src

smoke:
	python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=2).read()"
