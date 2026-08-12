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
uv run inv watch
```

Reruns the suite on every `.py` save, stops at the first failure, and runs the
previously-failed tests first (`-x --ff`). Leave it running in a second pane while you
work: write a failing test, watch it go red, make it green, refactor.

## Other commands

Tasks are defined in `tasks.py` and run with [Invoke](https://www.pyinvoke.org/).
`uv run inv --list` shows them all.

| Command | What it does |
|---|---|
| `uv run inv test` | Run the suite once |
| `uv run inv lint` | `ruff check --fix` |
| `uv run inv fmt` | `ruff format` |
| `uv run inv check` | Format check + lint + tests (what CI would run) |
| `uv run inv install` | `uv sync` |

`inv` is Invoke's short alias for `invoke`; either works.

## Layout

```
src/remotemobprogramming/   # the package — installed into the venv
tests/                      # tests import it the same way production code would
tasks.py                    # Invoke tasks (replaces a Makefile)
pyproject.toml              # deps, pytest, pytest-watcher and ruff config
```

The `src/` layout means tests can only import what's actually installed, so packaging
mistakes surface immediately instead of at release time.

## Adding dependencies

```sh
uv add requests          # runtime dependency
uv add --dev pytest-cov  # dev-only dependency
```
