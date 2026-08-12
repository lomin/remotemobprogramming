# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Getting the working tree into a known state without losing anything.

This is what lets `mob.drive` promise it always finishes: nothing here can
produce a conflict, because nothing here merges. Work that is in the way is
moved somewhere retrievable and reported, never replayed and never discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .config import BACKUP_PREFIX, Config
from .git import Git
from .session import stamp


class Sync(Enum):
    """How a local session branch stands against the remote."""

    NO_LOCAL = "no local branch"
    NO_REMOTE = "no remote branch"
    EQUAL = "in sync"
    BEHIND = "behind"
    AHEAD = "ahead"
    DIVERGED = "diverged"


@dataclass(frozen=True)
class SyncState:
    kind: Sync
    ahead: int = 0
    behind: int = 0


@dataclass(frozen=True)
class Stashed:
    paths: list[str]
    source: str | None
    label: str


def abort_in_progress(git: Git) -> list[str]:
    """Abandon any half-finished rebase / merge / cherry-pick / revert.

    Recovering a repository someone else left mid-conflict is part of the
    contract -- refusing to run because of a state we can safely abandon would
    be the tool breaking, not protecting.
    """
    git_dir = git.git_dir
    aborted: list[str] = []

    # rebase-apply is shared by `git am` and the apply-based rebase backend;
    # the `applying` marker is what tells them apart.
    if (git_dir / "rebase-apply" / "applying").exists():
        replaying = "am"
    elif (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        replaying = "rebase"
    else:
        replaying = None
    if replaying and _try_abort(git, replaying):
        aborted.append(replaying)

    for name, marker in (
        ("merge", "MERGE_HEAD"),
        ("cherry-pick", "CHERRY_PICK_HEAD"),
        ("revert", "REVERT_HEAD"),
    ):
        if (git_dir / marker).exists() and _try_abort(git, name):
            aborted.append(name)
    return aborted


def _try_abort(git: Git, operation: str) -> bool:
    if git.run(operation, "--abort", check=False).ok:
        return True
    # --quit clears the in-progress state while leaving HEAD alone. Unlike a
    # hard reset it cannot destroy uncommitted work, so it is the right last
    # resort when --abort itself fails.
    return git.run(operation, "--quit", check=False).ok


def stash_if_dirty(git: Git, label: str) -> Stashed | None:
    """Park uncommitted work, including untracked files.

    `--include-untracked` is not optional: an untracked file that a checkout
    would overwrite is exactly the failure this is meant to eliminate. Ignored
    files are left alone, so `.venv/` and friends stay where they are.
    """
    if not git.is_dirty():
        return None
    paths = git.status_paths()
    source = git.current_branch()
    git.run("stash", "push", "--include-untracked", "--quiet", "-m", label)
    return Stashed(paths=paths, source=source, label=label)


def classify(git: Git, branch: str, cfg: Config) -> SyncState:
    has_local = git.branch_exists(branch)
    has_remote = git.remote_branch_exists(branch, cfg.remote)

    if not has_remote:
        return SyncState(Sync.NO_REMOTE)
    if not has_local:
        return SyncState(Sync.NO_LOCAL)

    result = git.run(
        "rev-list",
        "--left-right",
        "--count",
        f"{branch}...{cfg.remote}/{branch}",
        check=False,
    )
    parts = result.stdout.split() if result.ok else []
    ahead, behind = (int(parts[0]), int(parts[1])) if len(parts) == 2 else (0, 0)

    if ahead and behind:
        return SyncState(Sync.DIVERGED, ahead, behind)
    if ahead:
        return SyncState(Sync.AHEAD, ahead, behind)
    if behind:
        return SyncState(Sync.BEHIND, ahead, behind)
    return SyncState(Sync.EQUAL)


def backup_name(branch: str, cfg: Config, when: datetime, taken) -> str:
    """`mob-backup/...`, deliberately outside the session prefix.

    Sessions are enumerated with a `refs/heads/<prefix>*` pattern, so a backup
    stored under that prefix would appear in `mob.list` as a phantom session.
    """
    slug = branch.removeprefix(cfg.prefix).replace("/", "-")
    base = f"{BACKUP_PREFIX}{slug}-at-{stamp(when)}"
    if not taken(base):
        return base
    suffix = 2
    while taken(f"{base}-{suffix}"):
        suffix += 1
    return f"{base}-{suffix}"


def backup(git: Git, branch: str, cfg: Config, when: datetime) -> str:
    name = backup_name(branch, cfg, when, git.branch_exists)
    git.run("branch", name, branch)
    return name


def switch_to(git: Git, branch: str, start_point: str | None = None) -> None:
    """Land on `branch`, resetting it to `start_point` when one is given.

    `switch -C` handles create, reset and checkout in one step, and works even
    when the branch being reset is the one already checked out.
    """
    if start_point:
        git.run("switch", "--quiet", "-C", branch, start_point)
    else:
        git.run("switch", "--quiet", branch)
