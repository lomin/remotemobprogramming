# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Settings, read from `[tool.mob]` in pyproject.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .git import Git

BACKUP_PREFIX = "mob-backup/"


@dataclass(frozen=True)
class Config:
    base: str | None = None
    prefix: str = "mob/"
    remote: str = "origin"
    notes_ref: str = "mob"

    @classmethod
    def load(cls, root: Path) -> Config:
        path = root / "pyproject.toml"
        if not path.is_file():
            return cls()
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        section = data.get("tool", {}).get("mob", {})
        return cls(
            base=section.get("base"),
            prefix=section.get("prefix", cls.prefix),
            remote=section.get("remote", cls.remote),
            notes_ref=section.get("notes_ref", cls.notes_ref),
        )

    @property
    def notes_fullref(self) -> str:
        return f"refs/notes/{self.notes_ref}"


def resolve_base(git: Git, cfg: Config, override: str | None = None) -> str:
    """Which branch `mob.start` opens a session from.

    Order: explicit flag, configured base, origin/HEAD, local main, current
    branch. Deliberately does no network round trip -- base detection should
    not be able to hang or fail.
    """
    for candidate in (override, cfg.base):
        if candidate:
            return candidate

    head = git.run(
        "symbolic-ref", "--quiet", "--short", f"refs/remotes/{cfg.remote}/HEAD", check=False
    ).stdout.strip()
    if head:
        return head.removeprefix(f"{cfg.remote}/")

    if git.branch_exists("main"):
        return "main"

    current = git.current_branch()
    if current:
        return current
    raise LookupError("cannot determine a base branch: HEAD is detached and 'main' is missing")
