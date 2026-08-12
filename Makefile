.PHONY: watch test lint fmt check install

## Run the TDD loop: reruns tests on every save, stops at first failure
watch:
	uv run ptw .

## Run the full test suite once
test:
	uv run pytest

## Lint (and auto-fix what is safely fixable)
lint:
	uv run ruff check --fix .

## Format
fmt:
	uv run ruff format .

## Everything CI would run
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run pytest

## Sync the venv with pyproject.toml / uv.lock
install:
	uv sync
