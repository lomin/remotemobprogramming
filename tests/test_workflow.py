# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""The session lifecycle, against real repositories."""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from remotemobprogramming.errors import MobError

BRANCH_RE = re.compile(r"^mob/\d{8}T\d{6}Z(-\d+)?$")


def note_json(mobber, anchor: str) -> dict:
    return json.loads(mobber.git("notes", "--ref=mob", "show", anchor))


# -- opening a session ------------------------------------------------------


def test_start_opens_a_timestamped_branch_off_the_base(alice):
    session = alice.mob.start()

    assert BRANCH_RE.match(session.branch)
    assert alice.branch() == session.branch


def test_start_leaves_an_anchor_commit_that_changes_nothing(alice):
    session = alice.mob.start()

    subject = alice.git("log", "-1", "--format=%s")
    assert subject == f"mob: session start {session.branch}"
    # Same tree as its parent: the anchor is a marker, not a change.
    assert alice.git("rev-parse", "HEAD^{tree}") == alice.git("rev-parse", "HEAD~1^{tree}")
    assert session.anchor == alice.git("rev-parse", "HEAD")


def test_start_parks_uncommitted_work_rather_than_carrying_it_to_the_base(alice):
    alice.write("wip.txt", "half an idea\n")

    alice.mob.start()

    assert not (alice.path / "wip.txt").exists()
    assert "stashed 1 uncommitted file" in alice.text
    assert "wip.txt" in alice.git("stash", "show", "--include-untracked", "--name-only")


def test_start_publishes_the_branch_and_its_note(alice, origin):
    session = alice.mob.start()

    assert (
        session.branch
        in subprocess.run(
            ["git", "branch", "--list", session.branch],
            cwd=origin,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert note_json(alice, session.anchor)["branch"] == session.branch


def test_a_new_session_has_no_parent(alice):
    session = alice.mob.start()

    assert note_json(alice, session.anchor)["parent"] is None


def test_start_accepts_a_name_up_front(alice):
    session = alice.mob.start(name="payments_spike")

    assert session.name == "payments_spike"
    assert note_json(alice, session.anchor)["name"] == "payments_spike"


def test_two_sessions_started_in_the_same_second_do_not_collide(alice):
    first = alice.mob.start()
    second = alice.mob.start()

    assert first.branch != second.branch
    # Commits are content-addressed. Identical trees, parents, messages and
    # timestamps would make these one commit -- and a shared anchor means a
    # shared note, so the second session would quietly erase the first.
    assert first.anchor != second.anchor


def test_both_sessions_survive_being_started_in_the_same_second(alice):
    alice.mob.start(name="older")
    alice.mob.start(name="newer")

    sessions, _ = _discover(alice)

    assert sorted(s.name for s in sessions) == ["newer", "older"]


def test_start_works_without_a_remote(solo):
    session = solo.mob.start()

    assert solo.branch() == session.branch
    assert note_json(solo, session.anchor)["branch"] == session.branch


# -- forking ----------------------------------------------------------------


def test_branch_forks_from_the_session_you_are_on(alice):
    parent = alice.mob.start()

    child = alice.mob.branch()

    assert child.branch != parent.branch
    assert note_json(alice, child.anchor)["parent"] == parent.anchor


def test_a_fork_from_a_plain_branch_is_a_root(alice):
    child = alice.mob.branch()

    assert note_json(alice, child.anchor)["parent"] is None


def test_forking_carries_uncommitted_work_onto_the_fork(alice):
    alice.mob.start()
    alice.write("wip.txt", "still thinking\n")

    alice.mob.branch()

    assert (alice.path / "wip.txt").read_text() == "still thinking\n"


def test_the_anchor_never_swallows_work_that_was_already_staged(alice):
    alice.mob.start()
    alice.write("wip.txt", "half an idea\n")
    alice.git("add", "-A")

    alice.mob.branch()

    # `git commit --allow-empty` would have committed the staged file; going
    # through commit-tree guarantees the marker is genuinely empty.
    assert alice.git("show", "--stat", "--format=", "HEAD") == ""
    assert "wip.txt" in alice.git("diff", "--cached", "--name-only")


def test_lineage_survives_three_levels(alice):
    first = alice.mob.start()
    second = alice.mob.branch()
    third = alice.mob.branch()

    assert note_json(alice, second.anchor)["parent"] == first.anchor
    assert note_json(alice, third.anchor)["parent"] == second.anchor


# -- handing over -----------------------------------------------------------


def test_next_commits_everything_and_pushes_the_same_branch(alice):
    session = alice.mob.start()
    alice.write("feature.py", "print('hi')\n")

    alice.mob.next()

    assert alice.branch() == session.branch, "a handover must not move you off the session"
    assert alice.git("log", "-1", "--format=%s") == "mob: next"
    assert alice.git("rev-parse", "HEAD") == alice.git("rev-parse", f"origin/{session.branch}")


def test_a_handover_says_what_it_is_waiting_on(alice):
    # Two network round trips -- the branch, then the note -- with git's own
    # output captured, so without this the terminal looks like it is idle.
    session = alice.mob.start()
    alice.write("feature.py", "x = 1\n")
    alice.clear()

    alice.mob.next()

    assert "staging the handover" in alice.text
    assert f"pushing {session.branch} to origin" in alice.text
    assert "publishing the session note" in alice.text


def test_taking_the_wheel_says_what_it_is_waiting_on(alice):
    alice.mob.start()
    alice.clear()

    alice.mob.drive()

    assert "fetching from origin" in alice.text
    assert "reading sessions" in alice.text


def test_next_respects_gitignore(alice):
    alice.mob.start()
    alice.write(".gitignore", "secret.txt\n")
    alice.write("secret.txt", "do not commit me\n")

    alice.mob.next()

    assert "secret.txt" not in alice.git("ls-files")


def test_next_takes_a_message(alice):
    alice.mob.start()
    alice.write("feature.py", "x = 1\n")

    alice.mob.next(message="add the thing")

    assert alice.git("log", "-1", "--format=%s") == "add the thing"


def test_next_with_nothing_to_commit_still_publishes(alice):
    session = alice.mob.start()
    alice.git("push", "--delete", "origin", session.branch)

    alice.mob.next()

    assert alice.git("rev-parse", "HEAD") == alice.git("rev-parse", f"origin/{session.branch}")
    assert "nothing new to commit" in alice.text


def test_next_refuses_on_a_branch_that_is_not_a_session(alice):
    with pytest.raises(MobError, match="not a mob session"):
        alice.mob.next()


# -- naming -----------------------------------------------------------------


def test_name_labels_the_session_you_are_on(alice):
    session = alice.mob.start()

    alice.mob.name("payments_spike")

    assert note_json(alice, session.anchor)["name"] == "payments_spike"


def test_a_session_can_be_renamed_without_disturbing_its_lineage(alice):
    parent = alice.mob.start()
    child = alice.mob.branch()

    alice.mob.name("second_thoughts", target=parent.branch)

    assert note_json(alice, parent.anchor)["name"] == "second_thoughts"
    assert note_json(alice, child.anchor)["parent"] == parent.anchor


def test_a_session_can_be_named_by_its_own_name(alice):
    alice.mob.start(name="first")

    alice.mob.name("second", target="first")

    sessions, _ = _discover(alice)
    assert [s.name for s in sessions] == ["second"]


def test_naming_a_branch_that_is_not_a_session_is_refused(alice):
    with pytest.raises(MobError, match="not on a mob session"):
        alice.mob.name("whatever")


# -- metadata really travels ------------------------------------------------


def test_a_second_mobber_sees_the_names_and_the_lineage(alice, bob):
    parent = alice.mob.start(name="groundwork")
    alice.mob.branch(name="offshoot")

    bob.mob.list()

    assert "groundwork" in bob.text
    assert "offshoot" in bob.text
    sessions, _ = _discover(bob)
    child = next(s for s in sessions if s.name == "offshoot")
    assert child.parent == parent.anchor


def test_a_fresh_clone_rebuilds_the_tree_from_notes_alone(alice, clone_as):
    alice.mob.start(name="groundwork")
    alice.mob.branch(name="offshoot")

    carol = clone_as("carol")
    carol.mob.list()

    assert "groundwork" in carol.text
    assert "offshoot" in carol.text


def test_list_marks_the_session_you_are_on(alice):
    alice.mob.start(name="current_thread")

    alice.mob.list()

    assert "current_thread" in alice.text
    assert "●" in alice.text


def test_list_says_so_when_there_is_nothing_yet(alice):
    alice.mob.list()

    assert "no mob sessions yet" in alice.text


# -- the exercise directory -------------------------------------------------


def test_the_exercise_directory_is_named_after_the_session(alice):
    alice.mob.start(name="tidal_ledger")
    (alice.path / "sessions" / "tidal_ledger").mkdir(parents=True)

    assert alice.mob.exercise_dir() == alice.path / "sessions" / "tidal_ledger"


def test_an_unnamed_session_has_nowhere_to_put_an_exercise(alice):
    alice.mob.start()

    with pytest.raises(MobError, match="the name is the package name"):
        alice.mob.exercise_dir()


def test_a_session_without_an_exercise_says_how_to_get_one(alice):
    alice.mob.start(name="tidal_ledger")

    with pytest.raises(MobError, match="no exercise yet") as caught:
        alice.mob.exercise_dir()

    assert "inv leetcode" in caught.value.hint


def test_there_is_no_exercise_outside_a_session(alice):
    with pytest.raises(MobError, match="not a mob session"):
        alice.mob.exercise_dir()


def _discover(mobber):
    from remotemobprogramming.session import discover

    return discover(mobber.mob.git, mobber.mob.cfg)
