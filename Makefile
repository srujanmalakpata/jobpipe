# Convenience targets. Everything runs in the project-local .venv managed by uv.
.PHONY: install lint format test run run-incremental live fixtures report tf-validate docker clean

install:
	uv sync --frozen --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest -q

# Fixture mode (default): extract -> dbt build -> report into ./data
run:
	uv run pipeline run

# Opt-in: real public job boards from config/boards.live.example.yaml into ./data/live
live:
	uv run pipeline run --live --data-dir data/live

fixtures:
	uv run python scripts/generate_fixtures.py

tf-validate:
	cd infra/gcp && terraform fmt -check -recursive && \
		terraform init -backend=false -input=false && terraform validate

docker:
	docker build -t jobpipe .

clean:
	rm -rf data transform/target transform/logs .pytest_cache .ruff_cache infra/gcp/.terraform
