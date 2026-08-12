# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""The six operations behind `inv mob.*`."""

from __future__ import annotations

import random
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from rich.console import Console

from .claude import Claude
from .config import Config, resolve_base
from .errors import MobError
from .git import Git
from .kata import (
    SCHEMA,
    SETTINGS,
    SOFT_WORDS,
    SYSTEM_PROMPT,
    Kata,
    KataRejected,
    build_prompt,
    summarise,
    words_in,
)
from .kata import parse as parse_kata
from .render import Ui
from .scaffold import ScaffoldError, build_and_prove
from .scaffold import install as scaffold_install
from .session import (
    Note,
    Session,
    anchor_message,
    discover,
    fetch_notes,
    latest,
    next_free_branch,
    publish_note,
    resolve,
    utcnow,
    validate_name,
)
from .tree import build_forest
from .worktree import Sync, abort_in_progress, backup, classify, stash_if_dirty, switch_to


class Mob:
    def __init__(
        self,
        git: Git | None = None,
        cfg: Config | None = None,
        ui: Ui | None = None,
        clock: Callable[[], datetime] = utcnow,
        rng: random.Random | None = None,
    ) -> None:
        self.git = git or Git()
        root = self.git.root
        self.git = Git(root)
        self.cfg = cfg or Config.load(root)
        self.ui = ui or Ui(Console())
        self.clock = clock
        # Seeded from the system, so two mobs asking for the same thing on the
        # same day do not get the same exercise.
        self.rng = rng or random.Random()

    # -- helpers ----------------------------------------------------------

    @property
    def remote(self) -> str:
        return self.cfg.remote

    def _has_remote(self) -> bool:
        return self.git.has_remote(self.remote)

    def _fetch(self) -> bool:
        """Refresh branches and notes. False when the remote is out of reach."""
        if not self._has_remote():
            return False
        ok = self.git.run("fetch", "--quiet", "--prune", self.remote, check=False).ok
        fetch_notes(self.git, self.cfg)
        return ok

    def _sessions(self) -> list[Session]:
        sessions, warnings = discover(self.git, self.cfg)
        for warning in warnings:
            self.ui.warn(warning)
        return sessions

    def _current_session(self, sessions: list[Session]) -> Session | None:
        branch = self.git.current_branch()
        return next((s for s in sessions if s.branch == branch), None) if branch else None

    def _anchor_commit(self, branch: str) -> str:
        """An empty commit on top of HEAD, made with plumbing.

        `git commit --allow-empty` would sweep up anything already staged; going
        through commit-tree guarantees the anchor's tree is identical to its
        parent's, so a session can be opened with work in progress without that
        work silently landing in the marker commit.
        """
        tree = self.git.out("rev-parse", "HEAD^{tree}")
        head = self.git.out("rev-parse", "HEAD")
        sha = self.git.out("commit-tree", tree, "-p", head, "-m", anchor_message(branch))
        # Moves the branch pointer only -- index and working tree are untouched.
        self.git.run("reset", "--soft", sha)
        return sha

    def _push_branch(self, branch: str) -> bool:
        if not self._has_remote():
            return False
        return self.git.run("push", "--quiet", "-u", self.remote, branch, check=False).ok

    def _taken(self, branch: str) -> bool:
        return self.git.branch_exists(branch) or self.git.remote_branch_exists(branch, self.remote)

    def _open_session(self, start_point: str, parent: str | None, name: str | None) -> Session:
        when = self.clock()
        branch = next_free_branch(self.cfg.prefix, when, self._taken)

        sessions = self._sessions()
        chosen = validate_name(name, sessions, self.git, self.cfg) if name else None

        switch_to(self.git, branch, start_point)
        anchor = self._anchor_commit(branch)

        note = Note(
            branch=branch,
            name=chosen,
            parent=parent,
            created=when,
            author=self.git.out("var", "GIT_COMMITTER_IDENT").rsplit(">", 1)[0] + ">",
        )
        published = publish_note(self.git, self.cfg, anchor, note)
        pushed = self._push_branch(branch)

        if self._has_remote() and not (pushed and published):
            self.ui.warn("could not reach the remote — this session is local for now")
            self.ui.hint("share it later:", "inv mob.next")

        return Session(anchor=anchor, branch=branch, note=note, is_current=True)

    # -- operations -------------------------------------------------------

    def start(self, name: str | None = None, base: str | None = None) -> Session:
        base_branch = resolve_base(self.git, self.cfg, base)
        self._fetch()
        abort_in_progress(self.git)

        stashed = stash_if_dirty(self.git, f"mob.start: from {self.git.current_branch()}")

        start_point = base_branch
        if self.git.remote_branch_exists(base_branch, self.remote):
            start_point = f"{self.remote}/{base_branch}"
        elif not self.git.branch_exists(base_branch):
            raise MobError(
                f"base branch {base_branch!r} does not exist",
                hint="set one with [tool.mob] base in pyproject.toml, or pass --base",
            )

        session = self._open_session(start_point, parent=None, name=name)

        self.ui.ok(f"session opened from {base_branch}")
        self.ui.session_headline(session, self.clock())
        if stashed:
            self.ui.stash_note(stashed)
        return session

    def branch(self, name: str | None = None) -> Session:
        current = self.git.current_branch()
        if not current:
            raise MobError(
                "HEAD is detached, so there is nothing to fork from",
                hint="check out a branch first, or use `inv mob.start`",
            )
        parent_session = self._current_session(self._sessions())
        parent = parent_session.anchor if parent_session else None

        # No stash: `switch -c` carries uncommitted work onto the fork, which is
        # what forking should do, and it cannot conflict.
        session = self._open_session(current, parent=parent, name=name)

        origin = parent_session.label if parent_session else current
        self.ui.ok(f"session forked from {origin}")
        self.ui.session_headline(session, self.clock())
        return session

    def list(self, all: bool = False, fetch: bool = True) -> None:
        if fetch:
            self._fetch()
        sessions = self._sessions()
        roots = build_forest(sessions, include_all=all)
        self.ui.sessions(roots, now=self.clock(), dirty=self.git.is_dirty(), prefix=self.cfg.prefix)

    def next(self, message: str | None = None) -> None:
        sessions = self._sessions()
        session = self._current_session(sessions)
        if not session:
            branch = self.git.current_branch() or "a detached HEAD"
            raise MobError(
                f"{branch} is not a mob session",
                hint="`inv mob.drive` to join one, or `inv mob.start` to open one",
            )

        self.git.run("add", "-A")
        staged = not self.git.run("diff", "--cached", "--quiet", check=False).ok
        if staged:
            self.git.run("commit", "--quiet", "-m", message or "mob: next")
            self.ui.ok("handover committed")
        else:
            self.ui.info("nothing new to commit")

        if not self._push_branch(session.branch):
            raise MobError(
                f"could not push {session.branch} to {self.remote}",
                hint="your work is committed locally — push again when you have a connection",
            )
        publish_note(self.git, self.cfg, session.anchor, session.note)
        self.ui.ok(f"pushed to {self.remote}/{session.branch}")
        self.ui.info(f"hand over with: inv mob.drive {session.label}")

    def drive(self, target: str | None = None) -> Session:
        """Land on a session, matching the remote, without losing anything."""
        online = self._fetch()
        if self._has_remote() and not online:
            self.ui.warn(f"could not reach {self.remote} — working from local refs")
            self.ui.info("what you get may be behind what the mob has pushed")

        aborted = abort_in_progress(self.git)
        for operation in aborted:
            self.ui.warn(f"abandoned an unfinished {operation}")

        sessions = self._sessions()
        session = resolve(target, sessions, self.cfg) if target else latest(sessions)
        if not session.exists:
            raise MobError(
                f"{session.label} has metadata but no branch left to check out",
                hint="it survives in `inv mob.list --all` only to keep its descendants' lineage",
            )

        stashed = stash_if_dirty(self.git, f"mob.drive: from {self.git.current_branch()}")
        state = classify(self.git, session.branch, self.cfg)
        backed_up: str | None = None

        remote_ref = f"{self.remote}/{session.branch}"
        if state.kind in (Sync.NO_LOCAL, Sync.BEHIND):
            switch_to(self.git, session.branch, remote_ref)
        elif state.kind is Sync.DIVERGED:
            backed_up = backup(self.git, session.branch, self.cfg, self.clock())
            switch_to(self.git, session.branch, remote_ref)
        else:
            switch_to(self.git, session.branch)

        if self.git.remote_branch_exists(session.branch, self.remote):
            self.git.run(
                "branch", "--quiet", f"--set-upstream-to={remote_ref}", session.branch, check=False
            )

        self.ui.session_headline(session, self.clock())
        if stashed:
            self.ui.stash_note(stashed)
        if backed_up:
            self.ui.backup_note(backed_up, state.ahead)

        if state.kind is Sync.AHEAD:
            plural = "" if state.ahead == 1 else "s"
            self.ui.warn(f"{state.ahead} unpushed commit{plural} kept")
            self.ui.hint("share them:", "inv mob.next")
        elif state.kind is Sync.NO_REMOTE:
            self.ui.warn(f"{self.remote} has no copy of this session yet")
            self.ui.hint("publish it:", "inv mob.next")
        else:
            self.ui.ok(f"in sync with {remote_ref}")
        return session

    def exercise_dir(self, must_exist: bool = True) -> Path:
        """The current session's exercise package.

        The session has to be named, because the name *is* the package name --
        that is the whole reason names are constrained to Python identifiers.
        """
        session = self._current_session(self._sessions())
        if not session:
            branch = self.git.current_branch() or "a detached HEAD"
            raise MobError(
                f"{branch} is not a mob session",
                hint="`inv mob.start` to open one",
            )
        if not session.name:
            raise MobError(
                f"{session.branch} has no name, and the name is the package name",
                hint="name it first: inv mob.name <name>",
            )

        path = self.git.root / self.cfg.sessions_dir / session.name
        if must_exist and not path.is_dir():
            raise MobError(
                f"{session.name} has no exercise yet",
                hint="scaffold one: inv leetcode '<what you feel like practising>'",
            )
        return path

    def leetcode(self, brief: str, attempts: int = 3) -> Kata:
        """Scaffold an exercise for this session from a free-form brief.

        Generation is not deterministic and the gates are strict, so a rejected
        attempt is retried once with the reason fed back in -- most rejections
        are a single fixable slip rather than a model that cannot do the job.
        """
        destination = self.exercise_dir(must_exist=False)
        if destination.exists():
            raise MobError(
                f"{destination.name} already has an exercise",
                hint="fork a session for another one: inv mob.branch --name <name>",
            )

        complaint: str | None = None
        for attempt in range(1, attempts + 1):
            if complaint:
                self.ui.warn(f"attempt {attempt - 1} rejected: {complaint}")
                self.ui.info("asking again")
            try:
                kata = self._generate(brief, complaint)
                with tempfile.TemporaryDirectory(prefix="mob-kata-") as workspace:
                    built = build_and_prove(
                        kata, destination.name, self.cfg.sessions_dir, Path(workspace)
                    )
                    scaffold_install(built, destination)
                break
            except (KataRejected, ScaffoldError) as rejection:
                if attempt == attempts:
                    raise
                complaint = rejection.message.removeprefix("the generated exercise was rejected: ")
                # The hint carries the tail of pytest's output, which is what
                # actually says *which* test went wrong and how. Sending back
                # only the headline asks the model to guess at its own mistake.
                if rejection.hint:
                    complaint += f"\n\n{rejection.hint}"

        if soft := words_in(kata, SOFT_WORDS):
            self.ui.soft_words(soft)

        self.ui.ok(f"{kata.difficulty} exercise scaffolded")
        self.ui.kata_headline(
            kata.title, kata.difficulty, str(destination.relative_to(self.git.root))
        )
        self.ui.hint("start the loop:", "inv watch")
        self.ui.hint("when it is green:", "inv test.submit")
        return kata

    def past_exercises(self, limit: int = 60) -> list[str]:
        """Every exercise this repository has ever produced, on any branch.

        Reading the working tree would only find the current branch's, and
        sessions are branches -- so the exercise a sibling session generated
        last week, which is exactly the one not to repeat, would be invisible.
        """
        refs = self.git.lines(
            "for-each-ref",
            "--format=%(refname)",
            f"refs/heads/{self.cfg.prefix}",
            f"refs/remotes/{self.remote}/{self.cfg.prefix}",
        )
        seen: dict[str, str] = {}
        for ref in refs:
            for path in self.git.lines(
                "ls-tree", "-r", "--name-only", ref, "--", self.cfg.sessions_dir
            ):
                if path.endswith("/main.py"):
                    seen.setdefault(path, ref)

        summaries: list[str] = []
        for path, ref in sorted(seen.items())[:limit]:
            source = self.git.run("show", f"{ref}:{path}", check=False)
            if source.ok and (summary := summarise(source.stdout)):
                summaries.append(summary)
        return summaries

    def _generate(self, brief: str, complaint: str | None = None) -> Kata:
        prompt = build_prompt(
            brief,
            already_done=self.past_exercises(),
            settings=self.rng.sample(SETTINGS, k=4),
            nonce=self.rng.randrange(1000, 10_000),
            complaint=complaint,
        )
        self.ui.info(f"asking claude ({self.cfg.model}) for an exercise…")
        payload = Claude(model=self.cfg.model).ask(prompt, SYSTEM_PROMPT, SCHEMA)
        return parse_kata(payload)

    def name(self, new_name: str, target: str | None = None) -> Session:
        sessions = self._sessions()
        session = resolve(target, sessions, self.cfg) if target else self._current_session(sessions)
        if not session:
            raise MobError(
                "not on a mob session, so there is nothing to name",
                hint="name another one with: inv mob.name <name> --session <branch>",
            )

        others = [s for s in sessions if s.anchor != session.anchor]
        chosen = validate_name(new_name, others, self.git, self.cfg)

        note = Note(
            branch=session.branch,
            name=chosen,
            parent=session.parent,
            created=session.note.created,
            author=session.note.author,
        )
        if not publish_note(self.git, self.cfg, session.anchor, note):
            self.ui.warn("named locally — the remote did not get the update")

        was = f" (was {session.name})" if session.name else ""
        self.ui.ok(f"{session.branch} is now {chosen}{was}")
        return Session(
            anchor=session.anchor,
            branch=session.branch,
            note=note,
            local=session.local,
            remote=session.remote,
            handovers=session.handovers,
            is_current=session.is_current,
        )


def open_mob(cwd: Path | str | None = None, console: Console | None = None) -> Mob:
    return Mob(git=Git(cwd), ui=Ui(console) if console else None)
