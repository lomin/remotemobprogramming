# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Thin wrapper around the git CLI.

Every git call in this package goes through here, which keeps the subprocess
details in one place and lets the tests drive real repositories instead of
mocking git's behaviour -- git's edge cases are the whole problem domain, so
faking them would be faking the thing under test.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """A git command exited non-zero."""

    def __init__(self, argv: list[str], returncode: int, stderr: str) -> None:
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"git {' '.join(argv)} exited {returncode}: {self.stderr}")


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Git:
    """Runs git in a working directory."""

    def __init__(self, cwd: Path | str | None = None) -> None:
        self.cwd = Path(cwd) if cwd else Path.cwd()

    # -- plumbing ---------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Never block on a credential prompt. A hung fetch would violate the
        # promise that mob.drive always finishes.
        env["GIT_TERMINAL_PROMPT"] = "0"
        env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
        return env

    def run(self, *argv: str, check: bool = True, stdin: str | None = None) -> Result:
        proc = subprocess.run(  # noqa: S603
            ["git", *argv],
            cwd=self.cwd,
            env=self._env(),
            input=stdin,
            capture_output=True,
            text=True,
        )
        result = Result(proc.returncode, proc.stdout, proc.stderr)
        if check and not result.ok:
            raise GitError(list(argv), proc.returncode, proc.stderr)
        return result

    def run_bytes(self, *argv: str, stdin: bytes | None = None) -> bytes:
        """Stdout as raw bytes. Needed for `cat-file --batch`, whose framing is
        byte-counted -- decoding first would desynchronise the parser on any
        non-ASCII author name."""
        proc = subprocess.run(  # noqa: S603
            ["git", *argv],
            cwd=self.cwd,
            env=self._env(),
            input=stdin,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise GitError(list(argv), proc.returncode, proc.stderr.decode("utf-8", "replace"))
        return proc.stdout

    def out(self, *argv: str, stdin: str | None = None) -> str:
        """Stdout, stripped. Raises on failure."""
        return self.run(*argv, stdin=stdin).stdout.strip()

    def lines(self, *argv: str) -> list[str]:
        text = self.out(*argv)
        return text.splitlines() if text else []

    def ok(self, *argv: str) -> bool:
        """True when the command exits zero. Never raises."""
        return self.run(*argv, check=False).ok

    # -- repository facts -------------------------------------------------

    @property
    def root(self) -> Path:
        return Path(self.out("rev-parse", "--show-toplevel"))

    @property
    def git_dir(self) -> Path:
        path = Path(self.out("rev-parse", "--absolute-git-dir"))
        return path

    def current_branch(self) -> str | None:
        """Branch name, or None when HEAD is detached."""
        result = self.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        return result.stdout.strip() or None

    def branch_exists(self, branch: str) -> bool:
        return self.ok("show-ref", "--verify", "--quiet", f"refs/heads/{branch}")

    def remote_branch_exists(self, branch: str, remote: str = "origin") -> bool:
        return self.ok("show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}")

    def has_remote(self, remote: str = "origin") -> bool:
        return remote in self.lines("remote")

    def rev_parse(self, rev: str) -> str | None:
        result = self.run("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
        return result.stdout.strip() or None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self.ok("merge-base", "--is-ancestor", ancestor, descendant)

    def is_dirty(self) -> bool:
        """Tracked modifications or untracked files. Ignored files don't count."""
        return bool(self.out("status", "--porcelain"))

    def status_paths(self) -> list[str]:
        return [line[3:] for line in self.lines("status", "--porcelain")]
