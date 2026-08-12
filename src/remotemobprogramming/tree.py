# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Arranging sessions into their lineage. Pure -- no git, no I/O.

An edge means "forked from", never "handed over to": handovers are commits
inside a session, so they never create structure here. Each session records at
most one parent, written once at creation and pointing at an anchor that
already existed, which is what makes this a forest rather than a graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .session import Session


@dataclass
class Node:
    session: Session
    children: list[Node] = field(default_factory=list)
    orphaned: bool = False
    """True when the recorded parent is not among the notes we can see -- the
    lineage is real but unreachable, so the node is shown as a root."""


def _sort_key(node: Node) -> tuple:
    return (node.session.last_activity, node.session.branch)


def build_forest(sessions: list[Session], include_all: bool = False) -> list[Node]:
    """Roots first, most recently active first, children the same way.

    By default a session whose branch is gone everywhere is dropped unless a
    surviving descendant needs it to hold the chain together.
    """
    by_anchor = {s.anchor: s for s in sessions}
    visible = _visible(by_anchor, include_all)

    nodes = {anchor: Node(by_anchor[anchor]) for anchor in visible}
    roots: list[Node] = []

    for anchor, node in nodes.items():
        parent = by_anchor[anchor].parent
        if parent is None:
            roots.append(node)
        elif parent in nodes:
            nodes[parent].children.append(node)
        else:
            node.orphaned = parent not in by_anchor
            roots.append(node)

    for node in nodes.values():
        node.children.sort(key=_sort_key, reverse=True)
    roots.sort(key=_sort_key, reverse=True)
    return roots


def _visible(by_anchor: dict[str, Session], include_all: bool) -> set[str]:
    if include_all:
        return set(by_anchor)

    keep = {anchor for anchor, session in by_anchor.items() if session.exists}
    for anchor in list(keep):
        keep |= _ancestors(anchor, by_anchor)
    return keep


def _ancestors(anchor: str, by_anchor: dict[str, Session]) -> set[str]:
    found: set[str] = set()
    current = by_anchor[anchor].parent
    while current and current in by_anchor and current not in found:
        found.add(current)
        current = by_anchor[current].parent
    return found


def walk(roots: list[Node]) -> list[tuple[Node, int]]:
    """Depth-first, with depth -- handy for flat renderings and for tests."""
    ordered: list[tuple[Node, int]] = []

    def visit(node: Node, depth: int) -> None:
        ordered.append((node, depth))
        for child in node.children:
            visit(child, depth + 1)

    for root in roots:
        visit(root, 0)
    return ordered
