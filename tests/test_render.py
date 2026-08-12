# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Output. rich renders to a StringIO, so this stays deterministic."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from rich.console import Console

# pytest puts the tests directory on sys.path, so the session builder is shared
# rather than duplicated.
from test_tree import session

from remotemobprogramming.render import LINGER, Ui, ago, duration, flatten
from remotemobprogramming.tree import build_forest

NOW = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)


def render(roots, **kwargs) -> str:
    output = StringIO()
    Ui(Console(file=output, width=200, no_color=True, highlight=False)).sessions(
        roots, now=NOW, **kwargs
    )
    return output.getvalue()


class Clock:
    """A clock the tests move by hand, so nothing has to sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def ui_on(*, terminal: bool, clock: Clock | None = None) -> tuple[Ui, StringIO]:
    output = StringIO()
    console = Console(
        file=output,
        width=200,
        no_color=True,
        highlight=False,
        force_terminal=terminal or None,
    )
    return Ui(console, clock=clock or Clock()), output


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=4), "4m ago"),
        (timedelta(hours=3), "3h ago"),
        (timedelta(days=2), "2d ago"),
    ],
)
def test_relative_times_read_like_a_person_wrote_them(delta, expected):
    assert ago(NOW - delta, NOW) == expected


def test_something_dated_in_the_future_does_not_read_as_negative():
    assert ago(NOW + timedelta(hours=1), NOW) == "just now"


def test_the_drawing_prefix_shows_which_child_is_last():
    roots = build_forest(
        [
            session("root"),
            session("first", parent="root", minutes=9),
            session("last", parent="root", minutes=1),
        ]
    )

    prefixes = [prefix for _, prefix in flatten(roots)]

    assert prefixes == ["", "├─ ", "└─ "]


def test_a_grandchild_is_indented_under_its_parent():
    roots = build_forest([session("a"), session("b", parent="a"), session("c", parent="b")])

    assert [prefix for _, prefix in flatten(roots)] == ["", "└─ ", "   └─ "]


def test_the_table_shows_the_branch_the_name_and_the_lineage():
    roots = build_forest([session("a", name="groundwork"), session("b", parent="a")])

    text = render(roots)

    assert "groundwork" in text
    assert "└─ b" in text


def test_the_shared_branch_prefix_is_stated_once_instead_of_on_every_row():
    text = render(build_forest([session("a")]))

    # The bare timestamp still resolves, so the shortened form stays usable.
    assert "(mob/…)" in text
    assert "mob/a" not in text


def test_the_last_handover_reads_as_one_fact():
    text = render(build_forest([session("a")]))

    assert "· Ada" in text


def test_an_unnamed_session_is_not_left_blank():
    assert "—" in render(build_forest([session("a")]))


def test_a_dirty_worktree_is_called_out_on_the_current_session():
    roots = build_forest([replace(session("a"), is_current=True)])

    assert "dirty" in render(roots, dirty=True)


def test_an_empty_list_offers_the_way_to_start():
    assert "inv mob.start" in render([])


# -- saying what is happening -----------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(3.2, "3s"), (42.0, "42s"), (105.0, "1m45s"), (61.0, "1m01s")],
)
def test_durations_read_like_a_person_wrote_them(seconds, expected):
    assert duration(seconds) == expected


def test_a_step_says_what_it_is_doing_while_it_does_it():
    ui, output = ui_on(terminal=True)

    with ui.step("asking claude (opus) for an exercise"):
        during = output.getvalue()

    assert "asking claude (opus) for an exercise" in during


def test_a_quick_step_leaves_nothing_behind():
    ui, output = ui_on(terminal=True)

    with ui.step("reading sessions"):
        pass

    # The live line is transient, so a fast command ends up looking exactly as
    # it did before any of this existed.
    assert "reading sessions" not in _printed(output)


def test_a_slow_step_leaves_a_receipt_with_the_time_it_took():
    clock = Clock()
    ui, output = ui_on(terminal=True, clock=clock)

    with ui.step("asking claude (opus)"):
        clock.advance(105.0)

    assert "asking claude (opus) 1m45s" in _printed(output)


def test_a_step_that_fails_leaves_no_receipt():
    clock = Clock()
    ui, output = ui_on(terminal=True, clock=clock)

    with pytest.raises(RuntimeError), ui.step("pushing to origin"):
        clock.advance(LINGER * 2)
        raise RuntimeError("no network")

    # The error is the message; a duration above it would only be in the way.
    assert "pushing to origin 10s" not in _printed(output)


def test_without_a_terminal_the_step_is_written_out_plainly():
    # Piped to a file or captured by a test: no spinner to animate, but the log
    # should still say where the time went.
    ui, output = ui_on(terminal=False)

    with ui.step("fetching from origin"):
        pass

    assert output.getvalue() == "  fetching from origin…\n"


def test_a_step_inside_a_step_borrows_the_one_display():
    # rich allows exactly one live display, so the nested call has to take over
    # the running one rather than start a second.
    ui, output = ui_on(terminal=True)

    with ui.step("scaffolding the exercise"), ui.step("checking it passes with its own solution"):
        inner = output.getvalue()
    restored = output.getvalue()

    assert "checking it passes with its own solution" in inner
    # And the outer message comes back when the inner one is done.
    assert restored.rindex("scaffolding the exercise") > restored.rindex("checking it passes")


def _printed(output: StringIO) -> str:
    """What survives on screen: the transient live line erases itself."""
    text = output.getvalue()
    return text.split("\x1b[2K")[-1]
