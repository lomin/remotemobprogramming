# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Turning a generated exercise into files, and proving them before they land.

Nothing here writes into the repository. The package is built in a temporary
directory and put through two gates first, because a generated exercise is
guilty until proven innocent:

1. With the real solution in place, every test passes. That is what makes the
   worked examples trustworthy -- an example whose expected answer is wrong
   would otherwise cost the mob an afternoon of making correct code satisfy an
   incorrect test, which is the worst failure this tool could have.
2. With the solution stripped back to `pass`, the package still imports and
   collects, and every single test fails. Collecting proves the skeleton is
   well-formed; all-red proves no test is vacuous. A test that passes against
   an empty method asserts nothing, and it would say nothing for the rest of
   the exercise.

Only then is the directory copied into place.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from .bench import QUIET
from .errors import MobError
from .kata import Kata

HEADER = "# Copyright (C) 2026 Steven Collins\n# SPDX-License-Identifier: AGPL-3.0-only\n"
COMMENT_WIDTH = 88
PYTEST_INI = """\
[pytest]
python_files = test_*.py *_test.py
markers =
    complexity: measures how a solution scales
addopts = -q --tb=short
"""


class ScaffoldError(MobError):
    pass


# How the caller says what is happening. Kept as a plain callable so this module
# knows nothing about the terminal, and the gates stay testable in silence.
Progress = Callable[[str], AbstractContextManager[None]]


def _silent(message: str) -> AbstractContextManager[None]:
    return nullcontext()


# -- stripping the solution -------------------------------------------------


def strip_solution(source: str, entry_point: str) -> str:
    """The solution reduced to its signature and `pass`.

    Rebuilt through the syntax tree rather than by slicing lines. A signature
    is free to wrap across lines, and a helper's body is free to look like
    anything, so counting lines gets this wrong the first time a solution is
    formatted differently than expected.

    Imports and private helpers are dropped, not stubbed. `from collections
    import deque` at the top of a skeleton announces the intended approach, and
    a stubbed `_expand_from_centre` gives away the decomposition.
    """
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if not classes:
        raise ScaffoldError("the solution has no `class Solution` to strip")

    solution = classes[0]
    methods = [
        node
        for node in solution.body
        if isinstance(node, ast.FunctionDef) and node.name == entry_point
    ]
    if not methods:
        raise ScaffoldError(f"the solution has no method called {entry_point!r}")

    method = methods[0]
    method.body = [ast.Pass()]
    method.decorator_list = []
    solution.body = [method]
    solution.decorator_list = []

    module = ast.Module(body=[solution], type_ignores=[])
    return ast.unparse(ast.fix_missing_locations(module))


# -- rendering --------------------------------------------------------------


def commented(text: str) -> str:
    """Prose as a `#` comment block, wrapped, blank lines kept."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("#")
            continue
        indent = len(paragraph) - len(paragraph.lstrip())
        wrapped = textwrap.wrap(
            paragraph.strip(),
            width=COMMENT_WIDTH - 2 - indent,
            break_long_words=False,
            break_on_hyphens=False,
        )
        lines += [f"# {' ' * indent}{line}" for line in wrapped or [""]]
    return "\n".join(lines)


def render_main(kata: Kata, *, solved: bool = False) -> str:
    """`main.py`: the problem as comments, then the skeleton.

    `solved=True` renders the real solution instead, which is what the first
    gate runs against.
    """
    body = kata.solution.strip() if solved else strip_solution(kata.solution, kata.entry_point)
    statement = f"{kata.title}  ({kata.difficulty})\n\n{kata.story.strip()}\n\n{kata.task.strip()}"
    statement += "\n\nConstraints:\n" + "\n".join(f"  - {line}" for line in kata.constraints)
    return f"{HEADER}{commented(statement)}\n\n\n{body}\n"


def render_test(kata: Kata, package: str) -> str:
    """`<name>_test.py`: one test per worked example, plus the scaling check."""
    parts = [
        HEADER,
        f'"""{kata.title} — the examples from the brief, and how it has to scale."""\n',
        "import random\n",
        "import pytest\n",
        "from remotemobprogramming.bench import assert_scales_like\n",
        f"from {package}.main import Solution\n",
        f"SIZES = {kata.sizes!r}\n",
        kata.generator.strip() + "\n",
    ]

    for example in kata.examples:
        # Wrapped here rather than left to the formatter: ruff formats code and
        # leaves docstrings alone, so a long one-liner would sit over the line
        # limit for as long as the exercise exists.
        why = textwrap.fill(
            example.why.strip(),
            width=COMMENT_WIDTH - 4,
            initial_indent="",
            subsequent_indent="    ",
        )
        parts.append(
            f"def test_{example.name}():\n"
            f'    """{why}"""\n'
            f"{textwrap.indent(example.code.strip(), '    ')}\n"
        )

    parts.append(
        "@pytest.mark.complexity\n"
        "def test_it_scales():\n"
        '    """The obvious answer is too slow. This is what says so."""\n'
        "    assert_scales_like(\n"
        f"        Solution().{kata.entry_point},\n"
        "        build=build,\n"
        "        sizes=SIZES,\n"
        f"        expected={kata.intended_complexity!r},\n"
        f"        beats={kata.brute_force_complexity!r},\n"
        "    )\n"
    )
    return "\n".join(parts)


def write_package(kata: Kata, root: Path, name: str, container: str, *, solved: bool) -> Path:
    """Lay the exercise out under `root/<container>/<name>/`.

    Every write says `utf-8` rather than taking the default. Python reads source
    files as UTF-8 whatever the platform, but `write_text` encodes with the
    locale's -- cp1252 on a stock Windows -- and a generated exercise is full of
    prose. One em dash in a title is enough to make the file it lands in
    unparseable, which fails the first gate for a reason that has nothing to do
    with the exercise.
    """
    package_root = root / container
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "__init__.py").write_text(HEADER, encoding="utf-8")

    directory = package_root / name
    directory.mkdir(exist_ok=True)
    (directory / "__init__.py").write_text(HEADER, encoding="utf-8")
    (directory / "main.py").write_text(render_main(kata, solved=solved), encoding="utf-8")
    (directory / f"{name}_test.py").write_text(
        render_test(kata, f"{container}.{name}"), encoding="utf-8"
    )
    return directory


# -- the gates --------------------------------------------------------------

COUNTS = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)")


@dataclass(frozen=True)
class Run:
    returncode: int
    output: str

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for number, word in COUNTS.findall(self.output):
            tally[word.rstrip("s")] = tally.get(word.rstrip("s"), 0) + int(number)
        return tally

    def count(self, word: str) -> int:
        return self.counts.get(word, 0)


def run_pytest(root: Path, target: Path, *extra: str, timeout: float = 600.0) -> Run:
    """Run pytest against the temporary copy, isolated from this repository."""
    (root / "pytest.ini").write_text(PYTEST_INI, encoding="utf-8")
    environment = {
        **os.environ,
        "PYTHONPATH": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        # The report we are about to read quotes the exercise back at us, em
        # dashes and all. Writing to a pipe, the child would otherwise encode it
        # with the locale's codec while we decode as UTF-8 below.
        "PYTHONIOENCODING": "utf-8",
        # The scaling test draws a spinner on the terminal, straight past this
        # capture. Our own spinner is already there saying which gate is
        # running, and two live displays on one terminal fight.
        QUIET: "1",
    }
    try:
        # This interpreter, not `uv run`: we are already inside the environment
        # that has both pytest and the bench harness, and going through uv would
        # add a resolve to every one of the three gate runs.
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-c", str(root / "pytest.ini"), str(target), *extra],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Run(returncode=124, output=f"pytest did not finish within {timeout:.0f}s")
    return Run(result.returncode, f"{result.stdout}\n{result.stderr}")


def gate_solved(root: Path, target: Path) -> None:
    """Every test passes against the real solution, scaling check included."""
    result = run_pytest(root, target)
    if result.returncode != 0 or result.count("passed") == 0:
        raise ScaffoldError(
            "the exercise does not pass against its own solution",
            hint=_tail(result.output),
        )


def gate_skeleton(root: Path, target: Path) -> None:
    """It still imports, and nothing passes."""
    collected = run_pytest(root, target, "--collect-only")
    if collected.returncode != 0:
        raise ScaffoldError(
            "the stripped skeleton does not import",
            hint=_tail(collected.output),
        )

    expected = len(re.findall(r"::test_", collected.output))
    result = run_pytest(root, target, "-m", "not complexity")
    passed = result.count("passed")
    if passed:
        raise ScaffoldError(
            f"{passed} test(s) pass with the solution stripped out, so they assert nothing",
            hint=_tail(result.output),
        )
    # One test is the scaling check, which this run deselected.
    if result.count("failed") < expected - 1:
        raise ScaffoldError(
            "the stripped skeleton does not fail cleanly",
            hint=_tail(result.output),
        )


def _tail(output: str, lines: int = 12) -> str:
    kept = [line for line in output.strip().splitlines() if line.strip()]
    return "\n".join(kept[-lines:])


def format_with_ruff(root: Path) -> None:
    """Best effort. A generated file that ruff cannot tidy is still usable."""
    for argv in (
        ["format", "--quiet", str(root)],
        ["check", "--quiet", "--fix", "--exit-zero", str(root)],
    ):
        subprocess.run([sys.executable, "-m", "ruff", *argv], capture_output=True, check=False)


def build_and_prove(
    kata: Kata,
    name: str,
    container: str,
    workspace: Path,
    *,
    progress: Progress = _silent,
) -> Path:
    """Render, gate, and hand back the directory ready to be copied into place."""
    write_package(kata, workspace, name, container, solved=True)
    directory = workspace / container / name
    # Three pytest runs, the first of which measures how the solution scales.
    # Minutes can pass here, so the caller gets to say so.
    with progress("checking it passes with its own solution"):
        gate_solved(workspace, directory)

    # Formatted only here, so the second gate validates the exact text that
    # gets installed rather than something ruff has yet to touch.
    (directory / "main.py").write_text(render_main(kata, solved=False), encoding="utf-8")
    format_with_ruff(workspace)
    with progress("checking the skeleton fails"):
        gate_skeleton(workspace, directory)
    return directory


def install(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ScaffoldError(
            f"{destination.name} already has an exercise",
            hint="fork a fresh session for another one: inv mob.branch",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    init = destination.parent / "__init__.py"
    if not init.exists():
        init.write_text(HEADER, encoding="utf-8")
    shutil.copytree(source, destination)
