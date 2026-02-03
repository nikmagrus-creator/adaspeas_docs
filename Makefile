.PHONY: up down test fmt

up:
	docker compose up --build

down:
	docker compose down

test:
	python -m pytest -q
