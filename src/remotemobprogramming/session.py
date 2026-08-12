# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Sessions: what they are, how they are stored, how they are found.

A session is a branch. Its metadata -- friendly name and which session it was
forked from -- lives in a git note attached to the session's *anchor commit*,
an empty commit made when the session is created. Notes attach to commits, not
to branch refs, and a session branch's tip moves on every handover, so the
anchor is what gives the note somewhere permanent to live.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .config import Config
from .errors import MobError
from .git import Git

SCHEMA_VERSION = 1
TIMESTAMP_FMT = "%Y%m%dT%H%M%SZ"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def anchor_message(branch: str) -> str:
    """The anchor's commit message. It has to name the branch.

    Commits are content-addressed, so an anchor whose tree, parent, message,
    author and second all match another one *is* that other one. Two sessions
    opened from the same base in the same second would otherwise share a single
    commit -- and a session's identity is its anchor, so they would share a note
    as well, and the second would silently erase the first. The branch name is
    unique by construction, which makes the commit unique too.
    """
    return f"mob: session start {branch}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(when: datetime) -> str:
    """Branch-name timestamp. UTC, because a remote mob spans timezones and a
    branch name that means a different wall clock to each member is a bug."""
    return when.astimezone(UTC).strftime(TIMESTAMP_FMT)


def iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# The note
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Note:
    branch: str
    name: str | None
    parent: str | None
    created: datetime
    author: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "v": SCHEMA_VERSION,
                "branch": self.branch,
                "name": self.name,
                "parent": self.parent,
                "created": iso(self.created),
                "author": self.author,
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> Note:
        data = json.loads(text)
        version = data.get("v")
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported note schema v{version}")
        return cls(
            branch=data["branch"],
            name=data.get("name"),
            parent=data.get("parent"),
            created=datetime.fromisoformat(data["created"]),
            author=data.get("author", ""),
        )

    def renamed(self, name: str) -> Note:
        return Note(self.branch, name, self.parent, self.created, self.author)


@dataclass(frozen=True)
class NoteScan:
    by_anchor: dict[str, Note]
    warnings: list[str] = field(default_factory=list)


def read_notes(git: Git, cfg: Config) -> NoteScan:
    """Every note in the mob ref, in two git calls.

    `git notes list` exits zero with empty output when the ref does not exist,
    so a repo that has never had a session needs no special case.
    """
    listing = git.lines("notes", f"--ref={cfg.notes_ref}", "list")
    pairs: list[tuple[str, str]] = []
    for line in listing:
        parts = line.split()
        if len(parts) == 2:
            pairs.append((parts[0], parts[1]))
    if not pairs:
        return NoteScan({})

    payload = "".join(f"{blob}\n" for blob, _ in pairs).encode()
    raw = git.run_bytes("cat-file", "--batch", stdin=payload)

    notes: dict[str, Note] = {}
    warnings: list[str] = []
    for (_, anchor), body in zip(pairs, _batch_bodies(raw), strict=False):
        try:
            notes[anchor] = Note.from_json(body.decode("utf-8"))
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            warnings.append(f"ignoring unreadable note on {anchor[:7]}: {exc}")
    return NoteScan(notes, warnings)


def _batch_bodies(raw: bytes) -> list[bytes]:
    """Split `git cat-file --batch` output into object bodies.

    The framing is `<sha> <type> <size>\\n<body>\\n`, byte-counted -- which is
    why this works on bytes rather than decoded text.
    """
    bodies: list[bytes] = []
    cursor = 0
    while cursor < len(raw):
        newline = raw.find(b"\n", cursor)
        if newline == -1:
            break
        header = raw[cursor:newline].split()
        cursor = newline + 1
        if len(header) < 3:  # "<sha> missing"
            continue
        size = int(header[2])
        bodies.append(raw[cursor : cursor + size])
        cursor += size + 1
    return bodies


def write_note(git: Git, cfg: Config, anchor: str, note: Note) -> None:
    git.run("notes", f"--ref={cfg.notes_ref}", "add", "-f", "-m", note.to_json(), anchor)


def fetch_notes(git: Git, cfg: Config) -> bool:
    """Force-fetch the notes ref. False when the remote is unreachable.

    Forcing is safe only because every write pushes immediately, so the local
    ref is never meaningfully ahead. See `publish_note`.
    """
    if not git.has_remote(cfg.remote):
        return False
    return git.run(
        "fetch", "--quiet", cfg.remote, f"+{cfg.notes_fullref}:{cfg.notes_fullref}", check=False
    ).ok


def publish_note(git: Git, cfg: Config, anchor: str, note: Note) -> bool:
    """Write a note and get it to the remote, surviving one lost race.

    On rejection we re-fetch (which overwrites our local notes ref) and then
    *re-apply* the note before pushing again -- re-applying is what stops the
    force-fetch from eating the write we just made.

    Returns whether the note reached the remote. Failing to publish is never
    fatal: the note is written locally either way, and being offline should
    not stop anyone starting a session.
    """
    write_note(git, cfg, anchor, note)
    if not git.has_remote(cfg.remote):
        return False
    if git.run("push", "--quiet", cfg.remote, cfg.notes_fullref, check=False).ok:
        return True

    fetch_notes(git, cfg)
    write_note(git, cfg, anchor, note)
    return git.run("push", "--quiet", cfg.remote, cfg.notes_fullref, check=False).ok


# ---------------------------------------------------------------------------
# Branches and sessions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BranchInfo:
    branch: str
    sha: str
    committed: datetime
    committer: str


def branch_infos(git: Git, cfg: Config) -> tuple[dict[str, BranchInfo], dict[str, BranchInfo]]:
    """Session branches, local and remote, with their tip facts."""
    fmt = "%(refname)%09%(objectname)%09%(committerdate:unix)%09%(committername)"
    patterns = [
        f"refs/heads/{cfg.prefix}*",
        f"refs/remotes/{cfg.remote}/{cfg.prefix}*",
    ]
    local: dict[str, BranchInfo] = {}
    remote: dict[str, BranchInfo] = {}
    local_prefix = "refs/heads/"
    remote_prefix = f"refs/remotes/{cfg.remote}/"

    for line in git.lines("for-each-ref", f"--format={fmt}", *patterns):
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        refname, sha, unix, committer = parts[0], parts[1], parts[2], parts[3]
        when = datetime.fromtimestamp(int(unix), UTC)
        if refname.startswith(local_prefix):
            branch = refname[len(local_prefix) :]
            local[branch] = BranchInfo(branch, sha, when, committer)
        elif refname.startswith(remote_prefix):
            branch = refname[len(remote_prefix) :]
            remote[branch] = BranchInfo(branch, sha, when, committer)
    return local, remote


@dataclass(frozen=True)
class Session:
    anchor: str
    branch: str
    note: Note
    local: BranchInfo | None = None
    remote: BranchInfo | None = None
    handovers: int = 0
    ahead: int = 0
    behind: int = 0
    is_current: bool = False

    @property
    def name(self) -> str | None:
        return self.note.name

    @property
    def parent(self) -> str | None:
        return self.note.parent

    @property
    def label(self) -> str:
        return self.name or self.branch

    @property
    def exists(self) -> bool:
        """False for a session whose branch has been deleted everywhere. Such a
        session still matters: it may be an ancestor holding the tree together."""
        return self.local is not None or self.remote is not None

    @property
    def tip(self) -> BranchInfo | None:
        candidates = [info for info in (self.local, self.remote) if info]
        return max(candidates, key=lambda info: info.committed) if candidates else None

    @property
    def last_activity(self) -> datetime:
        tip = self.tip
        return tip.committed if tip else self.note.created

    @property
    def last_driver(self) -> str | None:
        tip = self.tip
        return tip.committer if tip else None

    @property
    def sync_state(self) -> str:
        if self.local and not self.remote:
            return "local only"
        if self.remote and not self.local:
            return "remote only"
        if not self.exists:
            return "deleted"
        if self.ahead and self.behind:
            return f"diverged {self.ahead}/{self.behind}"
        if self.ahead:
            return f"{self.ahead} unpushed"
        if self.behind:
            return f"{self.behind} behind"
        return "in sync"


def discover(git: Git, cfg: Config) -> tuple[list[Session], list[str]]:
    """Every session known to this clone, plus any warnings worth showing."""
    scan = read_notes(git, cfg)
    local, remote = branch_infos(git, cfg)
    current = git.current_branch()

    # A note records the branch it was created for, which makes the lookup a
    # dict hit rather than a history walk. It is an index, not the truth: the
    # ancestor check below is what confirms it, and anything that fails the
    # check is re-derived from history.
    claimed: dict[str, str] = {}
    for anchor, note in scan.by_anchor.items():
        branch = note.branch
        tip = local.get(branch) or remote.get(branch)
        if tip and git.is_ancestor(anchor, tip.sha) and branch not in claimed:
            claimed[branch] = anchor

    for branch in sorted(set(local) | set(remote)):
        if branch in claimed:
            continue
        anchor = _anchor_by_walking(git, branch, local, remote, set(scan.by_anchor))
        if anchor and anchor not in claimed.values():
            claimed[branch] = anchor

    sessions: list[Session] = []
    for anchor, note in scan.by_anchor.items():
        branch = next((b for b, a in claimed.items() if a == anchor), note.branch)
        info_local = local.get(branch)
        info_remote = remote.get(branch)
        sessions.append(
            Session(
                anchor=anchor,
                branch=branch,
                note=note,
                local=info_local,
                remote=info_remote,
                handovers=_count(git, f"{anchor}..{(info_local or info_remote).sha}")
                if (info_local or info_remote)
                else 0,
                **_divergence(git, info_local, info_remote),
                is_current=branch == current,
            )
        )
    return sessions, scan.warnings


def _anchor_by_walking(
    git: Git,
    branch: str,
    local: dict[str, BranchInfo],
    remote: dict[str, BranchInfo],
    anchors: set[str],
) -> str | None:
    """The newest annotated commit reachable from the branch.

    This is the actual definition of "the session this branch belongs to"; it
    is the fallback for a branch someone renamed by hand, where the note's
    cached branch field no longer matches.
    """
    info = local.get(branch) or remote.get(branch)
    if not info or not anchors:
        return None
    for sha in git.lines("rev-list", info.sha):
        if sha in anchors:
            return sha
    return None


def _count(git: Git, revrange: str) -> int:
    result = git.run("rev-list", "--count", revrange, check=False)
    return int(result.stdout.strip() or 0) if result.ok else 0


def _divergence(git: Git, local: BranchInfo | None, remote: BranchInfo | None) -> dict[str, int]:
    if not local or not remote:
        return {"ahead": 0, "behind": 0}
    result = git.run(
        "rev-list", "--left-right", "--count", f"{local.sha}...{remote.sha}", check=False
    )
    if not result.ok:
        return {"ahead": 0, "behind": 0}
    parts = result.stdout.split()
    if len(parts) != 2:
        return {"ahead": 0, "behind": 0}
    return {"ahead": int(parts[0]), "behind": int(parts[1])}


# ---------------------------------------------------------------------------
# Naming, resolving, choosing
# ---------------------------------------------------------------------------


def next_free_branch(prefix: str, when: datetime, taken) -> str:
    """`mob/<utc timestamp>`, suffixed if two sessions start in one second."""
    base = f"{prefix}{stamp(when)}"
    if not taken(base):
        return base
    suffix = 2
    while taken(f"{base}-{suffix}"):
        suffix += 1
    return f"{base}-{suffix}"


def validate_name(name: str, sessions: list[Session], git: Git, cfg: Config) -> str:
    """Names are typed as bare shell arguments and are accepted anywhere a
    branch name is, so they have to be incapable of impersonating one."""
    candidate = name.strip()
    # Checked before the charset rule so that pasting a branch name gets the
    # explanation rather than a generic complaint about the slash.
    if candidate.startswith(cfg.prefix):
        raise MobError(
            f"a session name cannot start with {cfg.prefix!r}",
            hint="that prefix is reserved for session branches",
        )
    if not NAME_RE.match(candidate):
        raise MobError(
            f"{name!r} is not a usable session name",
            hint="letters, digits, dot, dash, underscore; up to 40 characters",
        )
    if git.branch_exists(candidate) or git.remote_branch_exists(candidate, cfg.remote):
        raise MobError(
            f"{candidate!r} is already a branch in this repository",
            hint="pick a name that cannot be confused with a branch",
        )
    for session in sessions:
        if session.name and session.name.casefold() == candidate.casefold():
            raise MobError(
                f"{candidate!r} is already the name of {session.branch}",
                hint="session names have to be unique to stay unambiguous",
            )
    return candidate


def resolve(token: str, sessions: list[Session], cfg: Config) -> Session:
    """Accept a branch name or a session name, interchangeably."""
    for session in sessions:
        if session.branch == token:
            return session

    matches = [s for s in sessions if s.name and s.name.casefold() == token.casefold()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        listing = ", ".join(s.branch for s in matches)
        raise MobError(f"{token!r} matches more than one session: {listing}")

    prefixed = f"{cfg.prefix}{token}"
    for session in sessions:
        if session.branch == prefixed:
            return session

    known = [s.branch for s in sessions] + [s.name for s in sessions if s.name]
    close = difflib.get_close_matches(token, known, n=3, cutoff=0.4)
    raise MobError(
        f"no session matches {token!r}",
        hint=("did you mean: " + ", ".join(close)) if close else "see `inv mob.list`",
    )


def latest(sessions: list[Session]) -> Session:
    """The most recently updated live session -- who handed over last wins."""
    live = [s for s in sessions if s.exists]
    if not live:
        raise MobError(
            "no mob sessions found",
            hint="start one with `inv mob.start`",
        )
    return max(live, key=lambda s: (s.last_activity, s.branch))
