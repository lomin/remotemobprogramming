# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""`inv leetcode`, end to end against a real repository and a fake Claude.

The CLI is the only thing stubbed out. Everything downstream of it -- the
gates, the git state, the files on disk -- is real, because that is where the
mistakes would be.
"""

from __future__ import annotations

import copy

import pytest
from test_scaffold import SOLVED

from remotemobprogramming.errors import MobError
from remotemobprogramming.kata import KataRejected


@pytest.fixture
def fake_claude(monkeypatch):
    """Queue up payloads for successive calls, and record the prompts."""

    class Fake:
        def __init__(self) -> None:
            self.payloads: list[dict] = []
            self.prompts: list[str] = []

        def queue(self, *payloads: dict) -> None:
            self.payloads.extend(copy.deepcopy(p) for p in payloads)

        def __call__(self, *args, **kwargs):
            return self

        def ask(self, prompt: str, system: str, schema: dict) -> dict:
            self.prompts.append(prompt)
            if not self.payloads:
                raise AssertionError("claude was called more times than expected")
            return self.payloads.pop(0)

    fake = Fake()
    monkeypatch.setattr("remotemobprogramming.commands.Claude", fake)
    return fake


def broken(**overrides) -> dict:
    return {**copy.deepcopy(SOLVED), **overrides}


# -- what has to be true before we spend anything ---------------------------


def test_an_exercise_needs_a_session(alice, fake_claude):
    with pytest.raises(MobError, match="not a mob session"):
        alice.mob.leetcode("sliding windows")

    assert fake_claude.prompts == []


def test_an_exercise_needs_the_session_to_be_named(alice, fake_claude):
    alice.mob.start()

    with pytest.raises(MobError, match="the name is the package name"):
        alice.mob.leetcode("sliding windows")

    assert fake_claude.prompts == []


def test_a_session_that_already_has_one_is_left_alone(alice, fake_claude):
    alice.mob.start(name="tidal_ledger")
    (alice.path / "sessions" / "tidal_ledger").mkdir(parents=True)

    with pytest.raises(MobError, match="already has an exercise"):
        alice.mob.leetcode("sliding windows")

    # Nothing was asked for, so nothing was paid for.
    assert fake_claude.prompts == []


# -- the happy path ---------------------------------------------------------


def test_the_exercise_lands_in_the_session_package(alice, fake_claude):
    fake_claude.queue(SOLVED)
    alice.mob.start(name="tidal_ledger")

    kata = alice.mob.leetcode("something with a clever sweep")

    directory = alice.path / "sessions" / "tidal_ledger"
    assert kata.title == "The Tidal Ledger"
    assert (directory / "main.py").exists()
    assert (directory / "tidal_ledger_test.py").exists()
    assert (directory / "__init__.py").exists()


def test_what_lands_is_the_skeleton_and_not_the_answer(alice, fake_claude):
    fake_claude.queue(SOLVED)
    alice.mob.start(name="tidal_ledger")

    alice.mob.leetcode("something with a clever sweep")

    main = (alice.path / "sessions" / "tidal_ledger" / "main.py").read_text()
    assert "deque" not in main
    assert "pass" in main
    assert "harbour master" in main


def test_the_brief_reaches_claude(alice, fake_claude):
    fake_claude.queue(SOLVED)
    alice.mob.start(name="tidal_ledger")

    alice.mob.leetcode("prefix sums, on the hard side")

    assert "prefix sums, on the hard side" in fake_claude.prompts[0]


def test_exercises_already_done_are_named_so_they_are_not_repeated(alice, fake_claude):
    fake_claude.queue(SOLVED)
    (alice.path / "sessions" / "parcel_run").mkdir(parents=True)
    alice.mob.start(name="tidal_ledger")

    alice.mob.leetcode("anything")

    assert "parcel_run" in fake_claude.prompts[0]


def test_the_mob_is_told_what_to_run_next(alice, fake_claude):
    fake_claude.queue(SOLVED)
    alice.mob.start(name="tidal_ledger")
    alice.clear()

    alice.mob.leetcode("anything")

    assert "inv watch" in alice.text
    assert "inv test.submit" in alice.text


def test_the_exercise_is_ready_to_be_handed_over(alice, fake_claude):
    # It has to survive `mob.next`, which is how the next driver gets it.
    fake_claude.queue(SOLVED)
    alice.mob.start(name="tidal_ledger")

    alice.mob.leetcode("anything")
    alice.mob.next(message="scaffold the exercise")

    assert "sessions/tidal_ledger/main.py" in alice.git("ls-tree", "-r", "--name-only", "HEAD")


# -- when the first attempt is no good --------------------------------------


def test_a_rejected_attempt_is_retried_with_the_reason(alice, fake_claude):
    fake_claude.queue(broken(intended_complexity="n", brute_force_complexity="n log n"), SOLVED)
    alice.mob.start(name="tidal_ledger")

    alice.mob.leetcode("anything")

    assert len(fake_claude.prompts) == 2
    assert "too close to tell apart" in fake_claude.prompts[1]
    assert (alice.path / "sessions" / "tidal_ledger" / "main.py").exists()


def test_a_second_rejection_gives_up_rather_than_burning_tokens(alice, fake_claude):
    giveaway = broken(task="Return the maximum sum of any subarray of that length.")
    fake_claude.queue(giveaway, giveaway)
    alice.mob.start(name="tidal_ledger")

    with pytest.raises(KataRejected, match="gives the technique away"):
        alice.mob.leetcode("anything")

    assert len(fake_claude.prompts) == 2


def test_nothing_is_left_behind_when_generation_fails(alice, fake_claude):
    # A half-written package would be swept up by the next `mob.next`.
    giveaway = broken(story="Slide a sliding window along the ledger.")
    fake_claude.queue(giveaway, giveaway)
    alice.mob.start(name="tidal_ledger")

    with pytest.raises(KataRejected):
        alice.mob.leetcode("anything")

    assert not (alice.path / "sessions" / "tidal_ledger").exists()
    assert alice.git("status", "--porcelain") == ""
