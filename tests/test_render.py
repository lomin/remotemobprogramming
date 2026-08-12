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

from remotemobprogramming.render import Ui, ago, flatten
from remotemobprogramming.tree import build_forest

NOW = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)


def render(roots, **kwargs) -> str:
    output = StringIO()
    Ui(Console(file=output, width=200, no_color=True, highlight=False)).sessions(
        roots, now=NOW, **kwargs
    )
    return output.getvalue()


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
