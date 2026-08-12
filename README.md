# remotemobprogramming

A Python 3.13 project managed with [uv](https://docs.astral.sh/uv/), set up for test-driven development.

## Setup

One command on a fresh clone:

```sh
source ./active.sh
```

Creates `.venv` if it is missing, installs the package plus dev tools, and activates the
venv so `inv`, `pytest` and `python` work without a prefix. `deactivate` when you're done.

It must be **sourced**, not executed — `./active.sh` would activate a subprocess that
immediately exits, leaving your shell untouched. The script refuses to run that way and
tells you so.

### Or skip activation entirely

```sh
uv run inv <task>
```

Works from a cold clone with no setup at all. Every invocation re-syncs against
`uv.lock`, so it can never run against a stale or missing venv — an activated shell
does not do that. If someone runs `uv add` while your shell is active, run `uv sync`
to catch up.

## The TDD loop

```sh
inv watch          # or: uv run inv watch
```

Reruns the suite on every `.py` save, stops at the first failure, and runs the
previously-failed tests first (`-x --ff`). Leave it running in a second pane while you
work: write a failing test, watch it go red, make it green, refactor.

## Other commands

Tasks are defined in `tasks.py` and run with [Invoke](https://www.pyinvoke.org/).
`inv --list` shows them all.

| Command | What it does |
|---|---|
| `inv test` | Run the suite once |
| `inv lint` | `ruff check --fix` |
| `inv fmt` | `ruff format` |
| `inv check` | Format check + lint + tests (what CI would run) |
| `inv install` | `uv sync` |

Prefix any of them with `uv run` if you'd rather not activate. `inv` is Invoke's short
alias for `invoke`; either works.

## Layout

```
active.sh                   # source it to set up + activate the venv
src/remotemobprogramming/   # the package — installed into the venv
tests/                      # tests import it the same way production code would
tasks.py                    # Invoke tasks
pyproject.toml              # deps, pytest, pytest-watcher and ruff config
```

The `src/` layout means tests can only import what's actually installed, so packaging
mistakes surface immediately instead of at release time.

## Adding dependencies

```sh
uv add requests          # runtime dependency
uv add --dev pytest-cov  # dev-only dependency
```
