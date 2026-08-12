import os
from shlex import quote

from invoke import Collection, Exit, task

from remotemobprogramming.commands import Mob
from remotemobprogramming.errors import MobError
from remotemobprogramming.render import Ui

# A pty is what lets pytest, ruff and ptw see a terminal, so they colour their
# output and redraw in place instead of dumping plain text down a pipe. Windows
# has no `pty` module at all and Invoke raises rather than quietly going without,
# so ask for one only where one exists.
PTY = os.name != "nt"


def _sh(text: str) -> str:
    """Quote one argument for the shell Invoke will hand the command to.

    `shlex.quote` is POSIX-only. On Windows Invoke runs through COMSPEC --
    cmd.exe -- where a single quote is an ordinary character rather than a
    quote, so `-m 'not complexity'` arrives at pytest as two arguments,
    `'not` and `complexity'`, and the marker expression never matches.
    """
    return quote(text) if os.name != "nt" else f'"{text}"'


# Spelled once: it appears in two tasks, and getting the quoting right is the
# whole point.
NOT_COMPLEXITY = _sh("not complexity")


def _run(action):
    """Turn a MobError into a readable message and a non-zero exit."""
    try:
        return action(Mob())
    except MobError as error:
        Ui().error(error.message, error.hint)
        raise Exit(code=1) from None


def _exercise():
    """The current session's exercise directory, as a shell-safe path."""
    return _sh(str(_run(lambda mob: mob.exercise_dir())))


@task
def watch(c):
    """Run the TDD loop over the current session's exercise."""
    # The scaling checks are minutes of measurement, so they have no business
    # in a loop that fires on every keystroke.
    path = _exercise()
    c.run(f"uv run ptw {path} {path} -m {NOT_COMPLEXITY}", pty=PTY)


@task(
    positional=["brief"],
    help={"brief": "What you feel like practising, in your own words"},
)
def leetcode(c, brief):
    """Scaffold an exercise for this session from a free-form brief.

    inv leetcode 'prefix sums, sliding windows, something on the hard side'
    """
    _run(lambda mob: mob.leetcode(brief))


@task
def lint(c):
    """Lint, auto-fixing what is safely fixable."""
    c.run("uv run ruff check --fix .", pty=PTY)


@task
def fmt(c):
    """Format the code."""
    c.run("uv run ruff format .", pty=PTY)


@task
def install(c):
    """Sync the venv with pyproject.toml / uv.lock."""
    c.run("uv sync", pty=PTY)


# --- tests -----------------------------------------------------------------
#
# Three audiences, three scopes. `self` is for people working on this tool;
# `run` and `submit` are for the mob working through an exercise, and never
# see another session's.


@task(name="self")
def test_self(c):
    """Check the mob tooling itself: format, lint, and its own suite."""
    c.run("uv run ruff format --check .", pty=PTY)
    c.run("uv run ruff check .", pty=PTY)
    c.run("uv run pytest tests", pty=PTY)


@task(name="run", default=True)
def test_run(c):
    """Run this session's exercise, without the scaling checks."""
    c.run(f"uv run pytest {_exercise()} -m {NOT_COMPLEXITY}", pty=PTY)


@task(name="submit")
def test_submit(c):
    """Run this session's exercise in full, scaling checks included."""
    # --verbosity=1 rather than -v: `-q` in addopts decrements the same counter,
    # so -v only cancels it out. Naming each test as it starts is what says the
    # half minute inside the scaling check is work rather than a hang.
    c.run(f"uv run pytest {_exercise()} --verbosity=1", pty=PTY)


# --- mob sessions ----------------------------------------------------------
#
# A session is a branch; a handover is a commit on it. Only `start` and
# `branch` create branches.


@task(help={"name": "Optional friendly name for the session", "base": "Branch to open from"})
def mob_start(c, name=None, base=None):
    """Open a new session from the base branch."""
    _run(lambda mob: mob.start(name=name, base=base))


@task(name="branch", help={"name": "Optional friendly name for the session"})
def mob_branch(c, name=None):
    """Fork a new session from the one you are on."""
    _run(lambda mob: mob.branch(name=name))


@task(
    name="list",
    help={
        "all": "Include sessions whose branch is gone",
        "no-fetch": "Skip the fetch and read local refs only",
    },
)
def mob_list(c, all=False, no_fetch=False):
    """Show the session tree."""
    _run(lambda mob: mob.list(all=all, fetch=not no_fetch))


@task(name="next", help={"message": "Commit message for this handover"})
def mob_next(c, message=None):
    """Hand over: commit everything and push to the session branch."""
    _run(lambda mob: mob.next(message=message))


# `session` is a flag rather than a positional because Invoke cannot express an
# optional positional: ParserContext.missing_positional_args decides both "may
# consume a bare token" and "is required" from the same `value is None` test.
# A bare `inv mob.drive` matters more than saving the flag, so that wins; `-s`
# keeps the named form short.
@task(name="drive", help={"session": "Branch or session name; omit for the latest"})
def mob_drive(c, session=None):
    """Take the wheel. Defaults to the most recently updated session."""
    _run(lambda mob: mob.drive(session))


@task(
    name="name",
    help={
        "new-name": "The friendly name to give it",
        "session": "Session to rename; defaults to the one you are on",
    },
)
def mob_name(c, new_name, session=None):
    """Give a session a friendly name."""
    _run(lambda mob: mob.name(new_name, target=session))


mob = Collection("mob")
mob.add_task(mob_start, name="start")
mob.add_task(mob_branch)
mob.add_task(mob_list)
mob.add_task(mob_next)
mob.add_task(mob_drive)
mob.add_task(mob_name)

test = Collection("test")
test.add_task(test_self)
test.add_task(test_run)
test.add_task(test_submit)

# Invoke stops auto-collecting module-level tasks once an explicit namespace
# exists, so every task has to be added here by hand.
namespace = Collection(watch, leetcode, lint, fmt, install)
namespace.add_collection(mob)
namespace.add_collection(test)
