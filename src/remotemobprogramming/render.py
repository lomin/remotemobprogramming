# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Terminal output.

The lineage is drawn with tree glyphs *inside* a table so the structure and the
per-session columns stay readable together -- a plain rich Tree cannot align
columns across depths.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .session import Session
from .tree import Node
from .worktree import Stashed


def ago(when: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    seconds = int((now - when).total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 86400 * 30:
        return f"{seconds // 86400}d ago"
    return when.astimezone().strftime("%Y-%m-%d")


def flatten(roots: list[Node]) -> list[tuple[Node, str]]:
    """Depth-first with the drawing prefix already built for each row."""
    rows: list[tuple[Node, str]] = []

    def visit(node: Node, prefix: str, last: bool, top: bool) -> None:
        if top:
            glyph = ""
            child_prefix = ""
        else:
            glyph = "└─ " if last else "├─ "
            child_prefix = prefix + ("   " if last else "│  ")
        rows.append((node, prefix + glyph))
        for index, child in enumerate(node.children):
            visit(child, child_prefix, index == len(node.children) - 1, top=False)

    for root in roots:
        visit(root, "", True, top=True)
    return rows


class Ui:
    """All output goes through here so tests can capture it."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    # -- primitives -------------------------------------------------------

    def line(self, text: str = "") -> None:
        self.console.print(text)

    def ok(self, message: str) -> None:
        self.console.print(f"[green]✓[/green] {message}")

    def info(self, message: str) -> None:
        self.console.print(f"  {message}")

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]![/yellow] {message}")

    def error(self, message: str, hint: str | None = None) -> None:
        self.console.print(f"[red]✗[/red] {message}")
        if hint:
            self.console.print(f"  [dim]{hint}[/dim]")

    def hint(self, label: str, command: str) -> None:
        self.console.print(f"  [dim]{label}[/dim]  [cyan]{command}[/cyan]")

    # -- sessions ---------------------------------------------------------

    def session_headline(self, session: Session, now: datetime | None = None) -> None:
        name = Text(session.label, style="bold cyan")
        self.console.print(Text("→ ", style="bold").append(name))
        if session.name:
            self.console.print(f"  [dim]{session.branch}[/dim]")
        driver = session.last_driver
        by = f" by {driver}" if driver else ""
        self.console.print(f"  [dim]last handover {ago(session.last_activity, now)}{by}[/dim]")

    def stash_note(self, stashed: Stashed) -> None:
        count = len(stashed.paths)
        source = f" from {stashed.source}" if stashed.source else ""
        plural = "" if count == 1 else "s"
        self.warn(f"stashed {count} uncommitted file{plural}{source}")
        self.hint("restore:", "git stash pop")

    # -- exercises --------------------------------------------------------

    def kata_headline(self, title: str, difficulty: str, path: str) -> None:
        self.console.print(Text("→ ", style="bold").append(Text(title, style="bold cyan")))
        self.console.print(f"  [dim]{difficulty}[/dim]  [dim]{path}[/dim]")

    def soft_words(self, words: set[str]) -> None:
        listed = ", ".join(sorted(words))
        self.warn(f"the brief uses {listed}")
        self.console.print(
            "  [dim]ordinary English, but check it does not give too much away[/dim]"
        )

    def backup_note(self, branch: str, commits: int) -> None:
        plural = "" if commits == 1 else "s"
        self.warn(f"diverged — {commits} local commit{plural} set aside")
        self.hint("recover:", f"git switch {branch}")

    def sessions(
        self,
        roots: list[Node],
        now: datetime | None = None,
        dirty: bool = False,
        prefix: str = "mob/",
    ) -> None:
        if not roots:
            self.info("no mob sessions yet")
            self.hint("start one:", "inv mob.start")
            return

        # SIMPLE_HEAD drops the vertical rules, which keeps the tree glyphs
        # reading as a tree instead of as cells, and stops the unlabelled
        # marker column from opening the table with an empty box.
        table = Table(
            box=box.SIMPLE_HEAD,
            title=f"mob sessions  [dim]({prefix}…)[/dim]",
            title_justify="left",
            title_style="bold",
            pad_edge=False,
            show_edge=False,
            padding=(0, 1),
        )
        table.add_column("", width=1, no_wrap=True)
        table.add_column("Branch", no_wrap=True, overflow="ellipsis")
        table.add_column("Session", style="cyan", no_wrap=True, overflow="ellipsis")
        # Time and driver are one fact -- who handed over, and when.
        table.add_column("Last handover", no_wrap=True, overflow="ellipsis")
        table.add_column("Handovers", justify="right", no_wrap=True)
        table.add_column("State", no_wrap=True)

        for node, glyphs in flatten(roots):
            session = node.session
            gone = not session.exists
            style = "dim" if gone else None

            state = session.sync_state
            if session.is_current and dirty:
                state = f"{state} · dirty"
            if node.orphaned:
                state = f"{state} · detached"

            # The shared prefix is in the title, not repeated on every row. The
            # bare timestamp is still a valid argument to every mob task.
            short = session.branch.removeprefix(prefix)

            when = ago(session.last_activity, now)
            handover = f"{when} · {session.last_driver}" if session.last_driver else when

            table.add_row(
                "[bold green]●[/bold green]" if session.is_current else "",
                Text(glyphs + short, style=style or ""),
                Text(session.name or "—", style=style or "cyan"),
                Text(handover, style=style or ""),
                Text(str(session.handovers), style=style or ""),
                Text(state, style=style or _state_style(state)),
            )
        self.console.print(table)


def _state_style(state: str) -> str:
    if state.startswith("in sync"):
        return "green"
    if "diverged" in state or "deleted" in state:
        return "red"
    return "yellow"
