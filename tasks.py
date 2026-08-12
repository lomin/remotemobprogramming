from invoke import Collection, Exit, task

from remotemobprogramming.commands import Mob
from remotemobprogramming.errors import MobError
from remotemobprogramming.render import Ui


@task
def watch(c):
    """Run the TDD loop: rerun tests on every save, stop at first failure."""
    c.run("uv run ptw .", pty=True)


@task
def test(c):
    """Run the full test suite once."""
    c.run("uv run pytest", pty=True)


@task
def lint(c):
    """Lint, auto-fixing what is safely fixable."""
    c.run("uv run ruff check --fix .", pty=True)


@task
def fmt(c):
    """Format the code."""
    c.run("uv run ruff format .", pty=True)


@task
def check(c):
    """Everything CI would run: format check, lint, tests."""
    c.run("uv run ruff format --check .", pty=True)
    c.run("uv run ruff check .", pty=True)
    c.run("uv run pytest", pty=True)


@task
def install(c):
    """Sync the venv with pyproject.toml / uv.lock."""
    c.run("uv sync", pty=True)


# --- mob sessions ----------------------------------------------------------
#
# A session is a branch; a handover is a commit on it. Only `start` and
# `branch` create branches.


def _run(action):
    """Turn a MobError into a readable message and a non-zero exit."""
    try:
        return action(Mob())
    except MobError as error:
        Ui().error(error.message, error.hint)
        raise Exit(code=1) from None


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

# Invoke stops auto-collecting module-level tasks once an explicit namespace
# exists, so every task has to be added here by hand.
namespace = Collection(watch, test, lint, fmt, check, install)
namespace.add_collection(mob)
