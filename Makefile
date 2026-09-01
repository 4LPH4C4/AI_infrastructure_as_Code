.PHONY: install bootstrap test lint format typecheck check doctor start stop restart status

install:
	uv sync --dev

bootstrap:
	./bootstrap/bootstrap-macos.sh

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy

check: lint typecheck test

doctor:
	./scripts/doctor.sh

start:
	./scripts/start.sh

stop:
	./scripts/stop.sh

restart:
	./scripts/restart.sh

status:
	./scripts/status.sh
