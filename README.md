# remotemobprogramming

A Python 3.13 project managed with [uv](https://docs.astral.sh/uv/), set up for test-driven development.

## Setup

```sh
uv sync
```

That creates `.venv` and installs the package in editable mode plus the dev tools. No
`activate` needed — `uv run <cmd>` uses the venv automatically.

## The TDD loop

```sh
make watch
```

Reruns the suite on every `.py` save, stops at the first failure, and runs the
previously-failed tests first (`-x --ff`). Leave it running in a second pane while you
work: write a failing test, watch it go red, make it green, refactor.

## Other commands

| Command | What it does |
|---|---|
| `make test` | Run the suite once |
| `make lint` | `ruff check --fix` |
| `make fmt` | `ruff format` |
| `make check` | Format check + lint + tests (what CI would run) |
| `make install` | `uv sync` |

## Layout

```
src/remotemobprogramming/   # the package — installed into the venv
tests/                      # tests import it the same way production code would
pyproject.toml              # deps, pytest, pytest-watcher and ruff config
```

The `src/` layout means tests can only import what's actually installed, so packaging
mistakes surface immediately instead of at release time.

## Adding dependencies

```sh
uv add requests          # runtime dependency
uv add --dev pytest-cov  # dev-only dependency
```
