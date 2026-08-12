# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Note format, naming rules, and resolving a token to a session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from remotemobprogramming.config import Config
from remotemobprogramming.errors import MobError
from remotemobprogramming.session import (
    BranchInfo,
    Note,
    Session,
    latest,
    next_free_branch,
    resolve,
    stamp,
    validate_name,
)

CFG = Config()
EPOCH = datetime(2026, 8, 12, 14, 30, 5, tzinfo=UTC)


class FakeGit:
    """Stands in for the two predicates validate_name needs."""

    def __init__(self, branches: set[str] | None = None) -> None:
        self.branches = branches or set()

    def branch_exists(self, branch: str) -> bool:
        return branch in self.branches

    def remote_branch_exists(self, branch: str, remote: str = "origin") -> bool:
        return branch in self.branches


def session(branch: str, name: str | None = None, *, minutes: int = 0) -> Session:
    when = EPOCH + timedelta(minutes=minutes)
    note = Note(branch=branch, name=name, parent=None, created=EPOCH, author="Ada")
    return Session(
        anchor=f"anchor-{branch}",
        branch=branch,
        note=note,
        local=BranchInfo(branch, "sha", when, "Ada"),
    )


# -- the note ---------------------------------------------------------------


def test_a_note_survives_a_round_trip():
    note = Note(branch="mob/x", name="spike", parent="abc", created=EPOCH, author="Ada <a@b.c>")

    assert Note.from_json(note.to_json()) == note


def test_an_unnamed_session_round_trips_too():
    note = Note(branch="mob/x", name=None, parent=None, created=EPOCH, author="Ada")

    assert Note.from_json(note.to_json()).name is None


def test_a_note_from_a_future_schema_is_refused_rather_than_guessed_at():
    with pytest.raises(ValueError, match="schema"):
        Note.from_json('{"v": 99, "branch": "mob/x", "created": "2026-01-01T00:00:00Z"}')


# -- branch naming ----------------------------------------------------------


def test_the_branch_name_is_a_utc_timestamp():
    assert stamp(EPOCH) == "20260812T143005Z"


def test_a_local_time_is_converted_to_utc_before_stamping():
    berlin = EPOCH.astimezone(UTC).replace(tzinfo=UTC)

    assert stamp(berlin) == stamp(EPOCH)


def test_two_sessions_in_the_same_second_get_distinct_branches():
    taken = {"mob/20260812T143005Z"}

    assert next_free_branch("mob/", EPOCH, taken.__contains__) == "mob/20260812T143005Z-2"


def test_the_suffix_keeps_climbing_while_names_are_taken():
    taken = {"mob/20260812T143005Z", "mob/20260812T143005Z-2"}

    assert next_free_branch("mob/", EPOCH, taken.__contains__) == "mob/20260812T143005Z-3"


# -- naming rules -----------------------------------------------------------


def test_a_plain_slug_is_accepted():
    assert validate_name("payments_spike", [], FakeGit(), CFG) == "payments_spike"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "has space",
        "_leading",
        "a" * 41,
        "sym$bol",
        "payments-spike",  # a dash is fine in a branch, illegal in an identifier
        "payments.spike",
        "Payments",  # packages are lower case
        "2sum",  # cannot start with a digit
    ],
)
def test_names_that_are_not_python_package_names_are_refused(bad):
    with pytest.raises(MobError, match="usable session name"):
        validate_name(bad, [], FakeGit(), CFG)


@pytest.mark.parametrize("bad", ["class", "lambda", "import"])
def test_a_name_cannot_be_a_python_keyword(bad):
    with pytest.raises(MobError, match="keyword"):
        validate_name(bad, [], FakeGit(), CFG)


@pytest.mark.parametrize("bad", ["heapq", "bisect", "queue", "statistics"])
def test_a_name_cannot_shadow_a_standard_library_module(bad):
    # These are exactly the words an algorithm session invites, and a package
    # of that name on sys.path shadows the real module for the whole repo.
    with pytest.raises(MobError, match="standard library"):
        validate_name(bad, [], FakeGit(), CFG)


def test_a_name_cannot_impersonate_a_session_branch():
    with pytest.raises(MobError, match="cannot start with"):
        validate_name("mob/whatever", [], FakeGit(), CFG)


def test_a_name_cannot_collide_with_a_real_branch():
    with pytest.raises(MobError, match="already a branch"):
        validate_name("main", [], FakeGit({"main"}), CFG)


def test_two_sessions_cannot_share_a_name():
    existing = [session("mob/a", name="spike")]

    with pytest.raises(MobError, match="already the name"):
        validate_name("spike", existing, FakeGit(), CFG)


def test_the_uniqueness_check_ignores_case():
    # New names are lower case by rule, but a note written before that rule
    # existed can still carry capitals, and it still has to block a collision.
    existing = [session("mob/a", name="Spike")]

    with pytest.raises(MobError, match="already the name"):
        validate_name("spike", existing, FakeGit(), CFG)


# -- resolution -------------------------------------------------------------


def test_a_branch_name_resolves():
    sessions = [session("mob/a"), session("mob/b")]

    assert resolve("mob/b", sessions, CFG).branch == "mob/b"


def test_a_session_name_resolves_case_insensitively():
    sessions = [session("mob/a", name="payments")]

    assert resolve("PAYMENTS", sessions, CFG).branch == "mob/a"


def test_a_bare_timestamp_resolves_without_the_prefix():
    sessions = [session("mob/20260812T143005Z")]

    assert resolve("20260812T143005Z", sessions, CFG).branch == "mob/20260812T143005Z"


def test_an_exact_branch_match_beats_a_name_match():
    # A name can never be created that collides with a branch, but a branch
    # created by hand could collide with an existing name -- the branch wins.
    sessions = [session("mob/a", name="mob/b"), session("mob/b")]

    assert resolve("mob/b", sessions, CFG).branch == "mob/b"


def test_an_unknown_token_suggests_near_misses():
    sessions = [session("mob/a", name="payments_spike")]

    with pytest.raises(MobError, match="no session matches") as caught:
        resolve("payments-spik", sessions, CFG)

    assert "payments_spike" in caught.value.hint


# -- picking the latest -----------------------------------------------------


def test_the_latest_session_is_the_one_handed_over_most_recently():
    sessions = [session("mob/old", minutes=1), session("mob/new", minutes=99)]

    assert latest(sessions).branch == "mob/new"


def test_a_tie_is_broken_by_branch_name_so_the_choice_is_stable():
    sessions = [session("mob/a", minutes=5), session("mob/b", minutes=5)]

    assert latest(sessions).branch == "mob/b"


def test_a_session_whose_branch_is_gone_is_never_driven():
    ghost = Session(
        anchor="x",
        branch="mob/gone",
        note=Note(branch="mob/gone", name=None, parent=None, created=EPOCH, author="Ada"),
    )

    with pytest.raises(MobError, match="no mob sessions"):
        latest([ghost])
