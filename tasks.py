from invoke import task


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
