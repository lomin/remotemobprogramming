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
inv mob.start --name payments_spike   # open a session off the base branch
# ... work ...
inv mob.next                          # hand over: commit everything, push
```

The next person picks it up:

```sh
inv mob.drive                         # join the most recently updated session
# ... work ...
inv mob.next                          # hand back
```

Or join a specific one with `inv mob.drive -s payments_spike`.

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
`inv mob.drive -s payments_spike`, `-s mob/20260812T143005Z` and `-s 20260812T143005Z` all mean
the same session.

A session name is also a **Python package name**, because `inv leetcode` scaffolds its exercise
into `sessions/<name>/`. So it has to be a legal, idiomatic module identifier: lower case,
starting with a letter, then letters, digits and underscores. Python keywords are rejected, and
so are standard-library module names — a package called `heapq` at the root of the repo would
shadow the real one for everything in it, and `heapq` is exactly the sort of word an algorithm
session invites.

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
●   ├─ 20260812T054539Z        flaky_test_hunt   1m ago · Ada            1   in sync
    └─ 20260812T054537Z        payments_spike    1m ago · Ada            1   in sync
       └─ 20260812T054537Z-2   deeper_dive       1m ago · Ada            1   in sync
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

Defaults live under `[tool.mob]` in `pyproject.toml` (`base`, `prefix`, `remote`, `notes_ref`,
`sessions_dir`, `model`).

## Exercises

```sh
inv mob.start --name tidal_ledger
inv leetcode 'prefix sums, sliding windows or two pointers — medium'
```

That asks Claude for a problem, and scaffolds `sessions/tidal_ledger/` with `main.py` (the
problem as comments, plus an empty typed skeleton) and `tidal_ledger_test.py` (one test per
worked example, plus a scaling check). The package is named after the session — which is why
session names have to be Python identifiers.

### LeetCode's rigour, Advent of Code's framing

LeetCode says *"given an integer array `nums`, return the maximum sum of any subarray of length
k"*. The data structure is the first noun in the sentence, so the technique is announced before
you finish reading. Advent of Code says the elves are counting calories and leaves the modelling
to you — and the modelling is most of the skill.

So exercises keep the tiers, the canonical algorithms, and the guarantee that a better-than-obvious
answer exists, but the statement is a story about a harbour master or a courier, comprehensible to
someone who doesn't program. Naming a technique, a data structure, or a complexity gets the whole
exercise thrown away and regenerated.

### Nothing lands unless it's proved

The generated package is built in a temporary directory and put through two gates first:

1. **With the real solution in place, every test passes.** This is what makes the worked examples
   trustworthy. An example with a wrong expected answer would otherwise cost the mob an afternoon
   of making correct code satisfy an incorrect test.
2. **With the solution stripped back to `pass`, it still imports and collects, and every test
   fails.** Collecting proves the skeleton is well-formed; all-red proves no test is vacuous — a
   test that passes against an empty method asserts nothing and will go on asserting nothing.

Only then is it copied into `sessions/`. A rejected attempt is retried once with the reason fed
back to Claude. The solution is never written to disk: `main.py` is rebuilt from the syntax tree
with the body replaced, and the imports and private helpers dropped, because
`from collections import deque` at the top of a skeleton announces the approach.

### The scaling check

```
@pytest.mark.complexity
def test_it_scales():
    assert_scales_like(Solution().longest_balanced_run, build=build, sizes=SIZES,
                       expected='n', beats='n^2')
```

It cannot assert a wall-clock budget, because that number belongs to the machine and would turn
red the moment the mob hands over to an older laptop. What belongs to the *algorithm* is the shape
of the curve, so the timings are remeasured from scratch on every run and candidate growth models
are fitted to them. A slower machine multiplies every point by the same constant, and a constant
factor is exactly what a fit absorbs.

The protocol matters: the ladder is climbed once as a warm-up, then sizes are visited round-robin
with alternating direction (cancelling thermal drift), each keeps its best round, GC is off inside
the timed region, and the input is rebuilt untimed before every call so an in-place solution never
gets its own leftovers.

**What it can and cannot settle.** Over three decades O(n log n) fits at an exponent near 1.1 and
O(n²) at 2.0 — easy. But O(n) also sits near 1.0–1.1, and the gap to O(n log n) is smaller than
the systematic error from cache effects alone: a genuinely linear pass over a million integers
measures *steeper* than linear once the working set leaves L3. So the assertion is never "this is
exactly O(n log n)". It is **"this is decisively better than the brute-force class"**, which only
asks the fit to separate classes a full degree apart. Exercises whose two complexities are closer
than that are rejected at generation time as untestable.

That climb is also the safety valve. Without it, a quadratic answer to a linear problem doesn't
fail this test — it runs for hours at the top of the ladder. The budget is scaled by a quick
measurement of the machine actually running it, so slower hardware gets proportionally longer
rather than failing correct work. In practice a correct solution finishes in about three seconds
and a brute-force one is rejected in about eight.

## Running the tests

```sh
inv watch          # the TDD loop, on this session's exercise
```

Reruns on every `.py` save, stops at the first failure, runs previously-failed tests first
(`-x --ff`), and never runs the scaling check — that's minutes of measurement, which has no place
in a loop that fires on every keystroke.

| Command | What it does |
|---|---|
| `inv test` / `inv test.run` | This session's exercise, without the scaling check |
| `inv test.submit` | This session's exercise in full, scaling check included |
| `inv test.self` | The mob tooling itself: format check, lint, and its own suite |
| `inv lint` | `ruff check --fix` |
| `inv fmt` | `ruff format` |
| `inv install` | `uv sync` |

`test.run` and `test.submit` are scoped strictly to the session you're on, so another session's
exercise can never turn your suite red. Prefix any of them with `uv run` if you'd rather not
activate. `inv` is Invoke's short alias for `invoke`; either works.

## Layout

```
active.sh                   # source it to set up + activate the venv
tasks.py                    # Invoke tasks — a thin shell over the package
pyproject.toml              # deps, [tool.mob], pytest, pytest-watcher and ruff config
tests/                      # tests import the package the same way production code would
sessions/<name>/            # generated exercises, one per named session
src/remotemobprogramming/
    git.py                  # every git call goes through here
    session.py              # notes, discovery, naming, resolution
    tree.py                 # the lineage forest — pure, no git
    worktree.py             # stash / abort / classify / back up
    render.py               # the terminal output
    commands.py             # the operations behind every task
    claude.py               # one-shot structured call to the CLI
    kata.py                 # what we ask for, and what we refuse to accept
    scaffold.py             # ast-strip, render, and the two gates
    bench.py                # measuring and judging how a solution scales
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
