.PHONY: install lint format test model image serve load-test

IMAGE ?= ne-demand-api:local
PORT ?= 8090

install:
	uv sync --all-extras

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

# Serving image: export the production model from the registry, then build.
model:
	uv run ne-demand export-model --out build/model

image: model
	docker build -t $(IMAGE) .

serve:
	docker run --rm -p 127.0.0.1:$(PORT):8080 -v "$(CURDIR)/data:/data:ro" -e NE_DATA_ROOT=/data $(IMAGE)

# PRD target: p95 under 200 ms locally. Run `make serve` in another terminal first.
load-test:
	uv run python scripts/load_test.py http://localhost:$(PORT)
