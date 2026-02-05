.PHONY: env up down test lint smoke

env:
	@test -f .env || cp .env.example .env

up: env
	docker compose up --build

down:
	docker compose down

test:
	PYTHONPATH=src python -m pytest -q || test $$? -eq 5

lint:
	python -m compileall -q src

smoke:
	python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=2).read()"
