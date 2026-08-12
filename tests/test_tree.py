# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""The lineage forest. Pure -- no git involved."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from remotemobprogramming.session import BranchInfo, Note, Session
from remotemobprogramming.tree import build_forest, walk

EPOCH = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def session(
    anchor: str,
    parent: str | None = None,
    *,
    minutes: int = 0,
    alive: bool = True,
    name: str | None = None,
) -> Session:
    branch = f"mob/{anchor}"
    when = EPOCH + timedelta(minutes=minutes)
    note = Note(branch=branch, name=name, parent=parent, created=EPOCH, author="Ada")
    tip = BranchInfo(branch, f"sha-{anchor}", when, "Ada") if alive else None
    return Session(anchor=anchor, branch=branch, note=note, local=tip)


def branches(nodes) -> list[str]:
    return [node.session.anchor for node, _ in walk(nodes)]


def test_a_session_with_no_parent_is_a_root():
    roots = build_forest([session("a")])

    assert [node.session.anchor for node in roots] == ["a"]
    assert roots[0].children == []


def test_a_fork_hangs_off_the_session_it_was_forked_from():
    roots = build_forest([session("a"), session("b", parent="a")])

    assert len(roots) == 1
    assert [child.session.anchor for child in roots[0].children] == ["b"]


def test_lineage_nests_to_any_depth():
    sessions = [session("a"), session("b", parent="a"), session("c", parent="b")]

    assert branches(build_forest(sessions)) == ["a", "b", "c"]


def test_siblings_are_ordered_by_most_recent_handover():
    sessions = [
        session("root"),
        session("stale", parent="root", minutes=5),
        session("fresh", parent="root", minutes=90),
    ]

    roots = build_forest(sessions)

    assert [child.session.anchor for child in roots[0].children] == ["fresh", "stale"]


def test_roots_are_ordered_by_most_recent_handover_too():
    roots = build_forest([session("older", minutes=1), session("newer", minutes=2)])

    assert [node.session.anchor for node in roots] == ["newer", "older"]


def test_a_deleted_session_is_hidden_when_nothing_depends_on_it():
    roots = build_forest([session("alive"), session("gone", alive=False)])

    assert [node.session.anchor for node in roots] == ["alive"]


def test_a_deleted_session_survives_as_a_ghost_to_keep_its_children_reachable():
    sessions = [
        session("gone", alive=False),
        session("child", parent="gone"),
    ]

    roots = build_forest(sessions)

    # The chain matters more than the dead node: dropping "gone" would make
    # "child" look like a root it never was.
    assert branches(roots) == ["gone", "child"]
    assert roots[0].session.exists is False


def test_include_all_shows_dead_sessions_that_nothing_depends_on():
    roots = build_forest([session("alive"), session("gone", alive=False)], include_all=True)

    assert sorted(node.session.anchor for node in roots) == ["alive", "gone"]


def test_a_session_whose_parent_is_unknown_becomes_a_flagged_root():
    roots = build_forest([session("child", parent="never-seen")])

    assert len(roots) == 1
    assert roots[0].orphaned is True


def test_walk_reports_depth():
    sessions = [session("a"), session("b", parent="a"), session("c", parent="b")]

    assert [depth for _, depth in walk(build_forest(sessions))] == [0, 1, 2]


def test_an_empty_repository_has_an_empty_forest():
    assert build_forest([]) == []
