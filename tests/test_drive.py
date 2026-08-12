# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""`mob.drive` against every state it promises to survive.

Three guarantees, asserted over and over: you end on the branch, the branch
matches origin, and nothing you had is gone for good.
"""

from __future__ import annotations

import pytest

from remotemobprogramming.errors import MobError

FUTURE = "2030-01-01T00:00:00Z"


def in_sync(mobber, branch: str) -> bool:
    return mobber.git("rev-parse", "HEAD") == mobber.git("rev-parse", f"origin/{branch}")


def handover(mobber, filename: str, text: str, monkeypatch=None, when: str | None = None):
    mobber.write(filename, text)
    if when and monkeypatch:
        monkeypatch.setenv("GIT_COMMITTER_DATE", when)
        monkeypatch.setenv("GIT_AUTHOR_DATE", when)
    mobber.mob.next()
    if when and monkeypatch:
        monkeypatch.delenv("GIT_COMMITTER_DATE")
        monkeypatch.delenv("GIT_AUTHOR_DATE")


# -- choosing what to drive -------------------------------------------------


def test_a_bare_drive_joins_the_session_with_the_newest_handover(alice, bob, monkeypatch):
    older = alice.mob.start(name="older")
    alice.mob.start(name="newer")

    alice.mob.drive("older")
    handover(alice, "work.py", "x = 1\n", monkeypatch, FUTURE)

    bob.mob.drive()

    assert bob.branch() == older.branch, "newest activity should win, not newest branch name"


def test_a_session_can_be_driven_by_its_branch_name(alice, bob):
    session = alice.mob.start()

    bob.mob.drive(session.branch)

    assert bob.branch() == session.branch


def test_a_session_can_be_driven_by_its_friendly_name(alice, bob):
    session = alice.mob.start(name="payments-spike")

    bob.mob.drive("payments-spike")

    assert bob.branch() == session.branch


def test_driving_something_unknown_says_so(alice, bob):
    alice.mob.start(name="payments-spike")

    with pytest.raises(MobError, match="no session matches"):
        bob.mob.drive("nonsense")


def test_driving_with_no_sessions_at_all_points_at_start(bob):
    with pytest.raises(MobError, match="no mob sessions"):
        bob.mob.drive()


# -- the reconcile table ----------------------------------------------------


def test_a_session_this_clone_has_never_seen_is_created_and_tracked(alice, bob):
    session = alice.mob.start()
    handover(alice, "work.py", "x = 1\n")

    bob.mob.drive()

    assert bob.branch() == session.branch
    assert in_sync(bob, session.branch)
    assert (bob.path / "work.py").exists()
    assert bob.git("rev-parse", "--abbrev-ref", "HEAD@{upstream}") == f"origin/{session.branch}"


def test_driving_a_session_already_in_sync_changes_nothing(alice, bob):
    session = alice.mob.start()
    bob.mob.drive()
    before = bob.git("rev-parse", "HEAD")

    bob.mob.drive()

    assert bob.git("rev-parse", "HEAD") == before
    assert in_sync(bob, session.branch)


def test_a_behind_session_fast_forwards_to_what_was_pushed(alice, bob):
    session = alice.mob.start()
    bob.mob.drive()

    handover(alice, "later.py", "y = 2\n")
    bob.mob.drive()

    assert in_sync(bob, session.branch)
    assert (bob.path / "later.py").exists()


def test_unpushed_commits_are_kept_rather_than_thrown_away(alice, bob):
    session = alice.mob.start()
    bob.mob.drive()
    bob.commit("mine.py", "mine = True\n")
    mine = bob.git("rev-parse", "HEAD")

    bob.mob.drive()

    assert bob.git("rev-parse", "HEAD") == mine, "strictly-ahead means unpushed handover work"
    assert (bob.path / "mine.py").exists()
    assert "1 unpushed commit kept" in bob.text
    assert bob.branch() == session.branch


def test_a_diverged_session_is_reset_to_origin_with_the_local_work_set_aside(alice, bob):
    session = alice.mob.start()
    bob.mob.drive()
    bob.commit("mine.py", "mine = True\n")
    mine = bob.git("rev-parse", "HEAD")

    handover(alice, "theirs.py", "theirs = True\n")
    bob.mob.drive()

    assert in_sync(bob, session.branch)
    assert (bob.path / "theirs.py").exists()
    backups = bob.git("branch", "--list", "mob-backup/*").split()
    assert backups, "divergent work must be recoverable"
    assert bob.git("rev-parse", backups[-1]) == mine
    assert "set aside" in bob.text


def test_a_backup_never_shows_up_as_a_session(alice, bob):
    alice.mob.start()
    bob.mob.drive()
    bob.commit("mine.py", "mine = True\n")
    handover(alice, "theirs.py", "theirs = True\n")
    bob.mob.drive()

    bob.clear()
    bob.mob.list()

    assert "mob-backup" not in bob.text


def test_a_session_the_remote_has_never_heard_of_still_works(alice):
    session = alice.mob.start()
    alice.git("push", "--delete", "origin", session.branch)

    alice.clear()
    alice.mob.drive(session.branch)

    assert alice.branch() == session.branch
    assert "no copy of this session yet" in alice.text


def test_driving_works_with_no_remote_configured(solo):
    session = solo.mob.start()
    solo.git("switch", "--quiet", "main")

    solo.mob.drive(session.branch)

    assert solo.branch() == session.branch


# -- states that break naive scripts ----------------------------------------


def test_uncommitted_changes_are_stashed_instead_of_blocking_the_switch(alice, bob):
    session = alice.mob.start()
    handover(alice, "work.py", "x = 1\n")
    bob.write("scratch.txt", "notes to self\n")

    bob.mob.drive()

    assert bob.branch() == session.branch
    assert in_sync(bob, session.branch)
    assert "stashed 1 uncommitted file" in bob.text


def test_an_untracked_file_in_the_way_of_the_checkout_does_not_stop_the_drive(alice, bob):
    session = alice.mob.start()
    handover(alice, "collision.py", "from alice\n")
    # Same path, untracked locally: a plain `git switch` refuses outright.
    bob.write("collision.py", "from bob, uncommitted\n")

    bob.mob.drive()

    assert bob.branch() == session.branch
    assert (bob.path / "collision.py").read_text() == "from alice\n"
    assert "stashed" in bob.text


def test_the_stash_is_reported_but_never_replayed(alice, bob):
    alice.mob.start()
    bob.write("scratch.txt", "notes to self\n")

    bob.mob.drive()

    assert not (bob.path / "scratch.txt").exists(), "popping could conflict; it stays parked"
    assert len(bob.git("stash", "list").splitlines()) == 1
    assert "git stash pop" in bob.text


def test_the_stash_records_which_session_it_came_from(alice, bob):
    alice.mob.start()
    bob.write("scratch.txt", "notes\n")

    bob.mob.drive()

    assert "mob.drive: from main" in bob.git("stash", "list")


def test_a_repository_left_mid_rebase_is_recovered_rather_than_refused(alice, bob):
    session = alice.mob.start()
    handover(alice, "work.py", "x = 1\n")

    bob.git("switch", "--quiet", "-c", "side")
    bob.commit("README.md", "side version\n")
    bob.git("switch", "--quiet", "main")
    bob.commit("README.md", "main version\n")
    bob.git("switch", "--quiet", "side")
    bob.git("rebase", "main", check=False)  # conflicts; leaves the repo mid-rebase
    assert (bob.path / ".git" / "rebase-merge").exists(), "precondition: repo really is stuck"

    bob.mob.drive()

    assert not (bob.path / ".git" / "rebase-merge").exists()
    assert bob.branch() == session.branch
    assert in_sync(bob, session.branch)
    assert "abandoned an unfinished rebase" in bob.text


def test_driving_the_session_you_are_already_on_is_a_plain_sync(alice, bob):
    session = alice.mob.start()
    bob.mob.drive()
    handover(alice, "more.py", "z = 3\n")

    bob.clear()
    bob.mob.drive(session.branch)

    assert bob.branch() == session.branch
    assert in_sync(bob, session.branch)
    assert (bob.path / "more.py").exists()


def test_driving_is_idempotent(alice, bob):
    alice.mob.start()
    handover(alice, "work.py", "x = 1\n")

    bob.mob.drive()
    first = bob.git("rev-parse", "HEAD")
    bob.mob.drive()

    assert bob.git("rev-parse", "HEAD") == first
    assert bob.git("stash", "list") == ""


def test_a_ghost_session_cannot_be_driven(alice):
    session = alice.mob.start()
    alice.git("switch", "--quiet", "main")
    alice.git("branch", "-D", session.branch)
    alice.git("push", "--delete", "origin", session.branch)

    with pytest.raises(MobError, match="no branch left"):
        alice.mob.drive(session.branch)
