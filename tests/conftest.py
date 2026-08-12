# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Fixtures that build real git repositories.

The mob tasks exist to survive git's awkward states, so the integration tests
drive git itself rather than a stand-in. Mocking here would only prove that the
mock behaves the way we already assumed.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from remotemobprogramming.commands import Mob
from remotemobprogramming.git import Git
from remotemobprogramming.render import Ui


@pytest.fixture(autouse=True)
def isolated_git_env(monkeypatch):
    """Keep the developer's own git config out of the tests."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Ada")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "ada@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Ada")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "ada@example.com")
    monkeypatch.delenv("GIT_COMMITTER_DATE", raising=False)
    monkeypatch.delenv("GIT_AUTHOR_DATE", raising=False)


def run(path: Path, *argv: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *argv],
        cwd=path,
        capture_output=True,
        text=True,
        check=check,
        env={**os.environ, **(env or {})},
    )
    return result.stdout.strip()


@dataclass
class Mobber:
    """One clone, plus the Mob bound to it and everything it printed."""

    path: Path
    mob: Mob
    output: StringIO

    @property
    def text(self) -> str:
        return self.output.getvalue()

    def clear(self) -> None:
        self.output.seek(0)
        self.output.truncate()

    def git(self, *argv: str, env: dict[str, str] | None = None, check: bool = True) -> str:
        return run(self.path, *argv, env=env, check=check)

    def branch(self) -> str:
        return self.git("symbolic-ref", "--short", "HEAD")

    def write(self, name: str, text: str) -> None:
        (self.path / name).write_text(text)

    def commit(self, name: str, text: str, when: str | None = None) -> None:
        self.write(name, text)
        self.git("add", "-A")
        env = {"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when} if when else None
        self.git("commit", "-m", f"work on {name}", env=env)


def _mobber(path: Path) -> Mobber:
    output = StringIO()
    console = Console(file=output, width=200, no_color=True, highlight=False)
    return Mobber(path=path, mob=Mob(git=Git(path), ui=Ui(console)), output=output)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    path = tmp_path / "origin.git"
    path.mkdir()
    run(path, "init", "--bare", "--initial-branch=main")
    return path


@pytest.fixture
def alice(tmp_path: Path, origin: Path) -> Mobber:
    path = tmp_path / "alice"
    path.mkdir()
    run(path, "init", "--initial-branch=main")
    run(path, "remote", "add", "origin", str(origin))
    (path / "README.md").write_text("# project\n")
    run(path, "add", "-A")
    run(path, "commit", "-m", "initial")
    run(path, "push", "-u", "origin", "main")
    return _mobber(path)


@pytest.fixture
def bob(tmp_path: Path, origin: Path, alice: Mobber) -> Mobber:
    path = tmp_path / "bob"
    run(tmp_path, "clone", "--quiet", str(origin), "bob")
    return _mobber(path)


@pytest.fixture
def clone_as(tmp_path: Path, origin: Path):
    """Make another clone of origin -- a third mobber, or a fresh checkout."""

    def make(name: str) -> Mobber:
        run(tmp_path, "clone", "--quiet", str(origin), name)
        return _mobber(tmp_path / name)

    return make


@pytest.fixture
def solo(tmp_path: Path) -> Mobber:
    """A repository with no remote at all."""
    path = tmp_path / "solo"
    path.mkdir()
    run(path, "init", "--initial-branch=main")
    (path / "README.md").write_text("# solo\n")
    run(path, "add", "-A")
    run(path, "commit", "-m", "initial")
    return _mobber(path)
