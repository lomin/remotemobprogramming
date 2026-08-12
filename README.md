# remotemobprogramming

Mob programming sessions as git branches, driven by [Invoke](https://www.pyinvoke.org/) tasks.
Inspired by [mob.sh](https://mob.sh/), but with sessions as first-class, named, long-lived
things that have a lineage.

A Python 3.13 project managed with [uv](https://docs.astral.sh/uv/), set up for test-driven
development.

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

## Mob sessions

**A branch is a session. A handover is a commit on it.** Only two commands ever create a
branch — everything else moves you between sessions or hands the wheel over inside one.

```sh
inv mob.start --name payments-spike   # open a session off the base branch
# ... work ...
inv mob.next                          # hand over: commit everything, push
```

The next person picks it up:

```sh
inv mob.drive                         # join the most recently updated session
# ... work ...
inv mob.next                          # hand back
```

Or join a specific one with `inv mob.drive -s payments-spike`.

Back and forth, for as long as the session lives. The branch name never changes; the handovers
pile up inside it.

### Commands

| Command | What it does |
|---|---|
| `inv mob.start [--name N] [--base B]` | Open a new session off the base branch |
| `inv mob.branch [--name N]` | **Fork** a new session off the one you're on |
| `inv mob.drive [-s SESSION]` | Take the wheel. Defaults to the newest handover |
| `inv mob.next [-m MSG]` | Hand over: stage everything, commit, push |
| `inv mob.name NAME [-s SESSION]` | Give a session a friendly name |
| `inv mob.list [--all] [--no-fetch]` | Show the session tree |

Anywhere a session is named you can use **either** the branch or the friendly name —
`inv mob.drive -s payments-spike`, `-s mob/20260812T143005Z` and `-s 20260812T143005Z` all mean
the same session.

> `-s` is a flag rather than a bare positional argument because Invoke cannot express an
> *optional* positional: the same check decides both whether a loose token may be consumed and
> whether the argument is required. A bare `inv mob.drive` is the common case, so it wins.

### Forking, and the tree

`inv mob.branch` forks a new session off the current one — the mob splitting, or spinning off a
variant without disturbing the thread you're on. That's the only thing that creates lineage, so
a tree edge always means *forked from*, never *handed over to*:

```
mob sessions  (mob/…)

    Branch                     Session           Last handover   Handovers   State
────────────────────────────────────────────────────────────────────────────────────
    20260812T054529Z           groundwork        1m ago · Ada            1   in sync
●   ├─ 20260812T054539Z        flaky-test-hunt   1m ago · Ada            1   in sync
    └─ 20260812T054537Z        payments-spike    1m ago · Ada            1   in sync
       └─ 20260812T054537Z-2   deeper-dive       1m ago · Ada            1   in sync
```

Each session records exactly one parent, written once when it's created and pointing at a
session that already existed. That's what keeps this a tree rather than a graph, no matter what
the commit history does.

### `mob.drive` always works

Joining a session is the command you run when someone has just handed over, so it is built not
to leave you stuck. It guarantees three things:

1. You end up on the session branch.
2. The branch matches `origin`.
3. Nothing you had is destroyed — anything moved out of the way is reported with the command
   to get it back.

**Nothing is ever merged or rebased**, which is what makes that hold: a conflict isn't a
possible outcome. It fetches, abandons any half-finished rebase or merge it finds, stashes
uncommitted work (including untracked files — ignored ones like `.venv/` are left alone), and
then reconciles by case:

| Your branch vs origin | What happens |
|---|---|
| Doesn't exist locally | Created from the remote, tracking |
| In sync | Nothing to do |
| Behind | Fast-forwarded |
| **Ahead only** | **Commits kept** — you're told to run `inv mob.next` |
| Diverged | Commits moved to a `mob-backup/…` branch, then reset to origin |

The stash is reported but never popped: popping can conflict, and when you drive to a *different*
session those changes belong to the one you left.

### Where the names and the lineage live

In a git note on the session's **anchor commit** — an empty commit made when the session opens.
Notes attach to commits rather than branch refs, and a session's tip moves on every handover, so
the anchor is what gives the metadata somewhere permanent to sit. The note travels with the repo
in `refs/notes/mob`, pushed on every write and fetched before every read, which is how a fresh
clone can reconstruct the whole tree.

Two consequences worth knowing: renaming a session while another mobber renames the same one
offline is last-push-wins, and sessions are never deleted for you — prune with `git branch -D`
plus `git push --delete`.

Defaults live under `[tool.mob]` in `pyproject.toml` (`base`, `prefix`, `remote`, `notes_ref`).

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
tasks.py                    # Invoke tasks — a thin shell over the package
pyproject.toml              # deps, [tool.mob], pytest, pytest-watcher and ruff config
tests/                      # tests import the package the same way production code would
src/remotemobprogramming/
    git.py                  # every git call goes through here
    session.py              # notes, discovery, naming, resolution
    tree.py                 # the lineage forest — pure, no git
    worktree.py             # stash / abort / classify / back up
    render.py               # the terminal output
    commands.py             # the six operations
```

The `src/` layout means tests can only import what's actually installed, so packaging
mistakes surface immediately instead of at release time.

## Adding dependencies

```sh
uv add requests          # runtime dependency
uv add --dev pytest-cov  # dev-only dependency
```

## Licence

Copyright (C) 2026 Steven Collins.

Licensed under the [GNU Affero General Public License v3.0 only](LICENSE)
(`AGPL-3.0-only`) — the strictest OSI-approved licence. Anything built on this must
stay open source under the same terms, and unlike the GPL that obligation is triggered
by **network use**, not just distribution: run a modified version as a service and you
must offer its users the corresponding source.

Note this is `-only`, not `-or-later` — recipients cannot switch to a future AGPL
version. Contributions are accepted under the same licence.
