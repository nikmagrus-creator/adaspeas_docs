.PHONY: up down test fmt

up:
	docker compose up --build

down:
	docker compose down

test:
	PYTHONPATH=src python -m pytest -q || test $$? -eq 5
