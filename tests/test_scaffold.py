# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Rendering an exercise, and the two gates it has to get through."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from test_kata import PAYLOAD

from remotemobprogramming.kata import parse
from remotemobprogramming.scaffold import (
    Run,
    ScaffoldError,
    build_and_prove,
    commented,
    install,
    render_main,
    render_test,
    strip_solution,
    write_package,
)

# A real linear solution, correct examples, and sizes big enough to measure.
# The one in test_kata is deliberately wrong, which is fine for validation but
# would never get past the first gate.
SOLVED = {
    **copy.deepcopy(PAYLOAD),
    "solution": (
        "from collections import deque\n"
        "\n"
        "\n"
        "class Solution:\n"
        "    def calmest_stretch(self, readings: list[int], span: int) -> int:\n"
        "        highs: deque[int] = deque()\n"
        "        lows: deque[int] = deque()\n"
        "        best = None\n"
        "        for right, value in enumerate(readings):\n"
        "            while highs and readings[highs[-1]] <= value:\n"
        "                highs.pop()\n"
        "            highs.append(right)\n"
        "            while lows and readings[lows[-1]] >= value:\n"
        "                lows.pop()\n"
        "            lows.append(right)\n"
        "            left = right - span + 1\n"
        "            if highs[0] < left:\n"
        "                highs.popleft()\n"
        "            if lows[0] < left:\n"
        "                lows.popleft()\n"
        "            if left >= 0:\n"
        "                spread = readings[highs[0]] - readings[lows[0]]\n"
        "                best = spread if best is None or spread < best else best\n"
        "        return best if best is not None else 0\n"
    ),
    "generator": (
        "def build(n, rng):\n    return ([rng.randrange(-10000, 10000) for _ in range(n)], 64)\n"
    ),
    "sizes": [4000, 16000, 64000, 256000],
}


@pytest.fixture
def kata():
    return parse(copy.deepcopy(SOLVED))


# -- stripping --------------------------------------------------------------


def test_the_skeleton_keeps_the_signature_exactly(kata):
    skeleton = strip_solution(kata.solution, kata.entry_point)

    assert "def calmest_stretch(self, readings: list[int], span: int) -> int:" in skeleton
    assert skeleton.rstrip().endswith("pass")


def test_the_skeleton_drops_the_imports():
    # `from collections import deque` at the top of a skeleton announces the
    # intended approach before anyone has read the problem.
    skeleton = strip_solution(SOLVED["solution"], "calmest_stretch")

    assert "deque" not in skeleton


def test_the_skeleton_drops_private_helpers():
    # A stubbed `_sweep` gives away the decomposition.
    source = (
        "class Solution:\n"
        "    def calmest_stretch(self, readings: list[int], span: int) -> int:\n"
        "        return self._sweep(readings, span)\n"
        "\n"
        "    def _sweep(self, readings: list[int], span: int) -> int:\n"
        "        return 0\n"
    )

    skeleton = strip_solution(source, "calmest_stretch")

    assert "_sweep" not in skeleton


def test_a_signature_that_wraps_across_lines_survives():
    # Slicing on line numbers would take the first line and lose the rest.
    source = (
        "class Solution:\n"
        "    def calmest_stretch(\n"
        "        self,\n"
        "        readings: list[int],\n"
        "        span: int = 3,\n"
        "    ) -> int:\n"
        "        return 0\n"
    )

    skeleton = strip_solution(source, "calmest_stretch")

    assert "readings: list[int]" in skeleton
    assert "span: int=3" in skeleton.replace(" = ", "=")


def test_a_body_on_the_signature_line_survives():
    source = "class Solution:\n    def go(self, xs: list[int]) -> int: return len(xs)\n"

    skeleton = strip_solution(source, "go")

    assert "def go(self, xs: list[int]) -> int:" in skeleton
    assert "len(xs)" not in skeleton


def test_a_docstring_is_not_left_behind_as_the_body():
    source = (
        "class Solution:\n"
        "    def go(self, xs: list[int]) -> int:\n"
        '        """Sort them and take the middle."""\n'
        "        return sorted(xs)[len(xs) // 2]\n"
    )

    skeleton = strip_solution(source, "go")

    assert "middle" not in skeleton


def test_a_solution_without_the_promised_method_is_refused():
    with pytest.raises(ScaffoldError, match="no method called"):
        strip_solution("class Solution:\n    def other(self) -> int:\n        return 0\n", "go")


# -- rendering --------------------------------------------------------------


def test_the_problem_is_in_the_source_as_comments(kata):
    main = render_main(kata)

    assert "# The Tidal Ledger  (medium)" in main
    assert "# Constraints:" in main
    assert "harbour master" in main


def test_the_rendered_skeleton_does_not_contain_the_answer(kata):
    main = render_main(kata)

    assert "deque" not in main
    assert "pass" in main


def test_the_solved_rendering_is_what_the_first_gate_runs(kata):
    assert "deque" in render_main(kata, solved=True)


def test_long_prose_is_wrapped_rather_than_run_off_the_screen():
    block = commented("word " * 60)

    assert all(len(line) <= 88 for line in block.splitlines())
    assert len(block.splitlines()) > 1


def test_blank_lines_between_paragraphs_are_kept():
    assert commented("one\n\ntwo") == "# one\n#\n# two"


def test_every_example_becomes_a_test(kata):
    rendered = render_test(kata, "sessions.tidal_ledger")

    for example in kata.examples:
        assert f"def test_{example.name}():" in rendered
        assert example.why in rendered


def test_the_test_module_imports_the_exercise_by_its_package_path(kata):
    assert "from sessions.tidal_ledger.main import Solution" in render_test(
        kata, "sessions.tidal_ledger"
    )


def test_the_scaling_check_is_marked_so_the_watch_loop_can_skip_it(kata):
    rendered = render_test(kata, "sessions.tidal_ledger")

    assert "@pytest.mark.complexity" in rendered
    assert "expected='n'" in rendered
    assert "beats='n^2'" in rendered


def test_the_package_is_importable(kata, tmp_path):
    directory = write_package(kata, tmp_path, "tidal_ledger", "sessions", solved=True)

    assert (directory / "__init__.py").exists()
    assert (directory.parent / "__init__.py").exists()
    assert (directory / "main.py").exists()
    assert (directory / "tidal_ledger_test.py").exists()


# -- reading pytest's summary -----------------------------------------------


def test_the_summary_is_read_off_the_output():
    result = Run(1, "...\n3 failed, 1 passed in 0.42s\n")

    assert result.count("failed") == 3
    assert result.count("passed") == 1


def test_a_summary_with_nothing_in_it_counts_zero():
    assert Run(0, "no tests ran in 0.01s").count("passed") == 0


# -- the gates --------------------------------------------------------------


def test_a_sound_exercise_gets_through_both_gates(kata, tmp_path):
    """The whole point of the pipeline, end to end.

    Slow, because it really does run pytest three times over a really measured
    scaling check. It is the only test here that proves the two gates agree
    with each other.
    """
    directory = build_and_prove(kata, "tidal_ledger", "sessions", tmp_path)

    assert (directory / "main.py").read_text().count("pass") == 1
    assert "deque" not in (directory / "main.py").read_text()


def test_an_example_with_the_wrong_answer_is_caught_by_the_first_gate(kata, tmp_path):
    # The failure this whole pipeline exists to prevent: an afternoon spent
    # making correct code satisfy an incorrect test.
    wrong = parse(
        {
            **copy.deepcopy(SOLVED),
            "examples": [
                {
                    "name": "the_worked_case",
                    "why": "from the ledger",
                    "code": "assert Solution().calmest_stretch([4, 9, 1, 2], 2) == 999",
                },
                *SOLVED["examples"][1:],
            ],
        }
    )

    with pytest.raises(ScaffoldError, match="does not pass against its own solution"):
        build_and_prove(wrong, "tidal_ledger", "sessions", tmp_path)


def test_a_test_that_asserts_nothing_is_caught_by_the_second_gate(kata, tmp_path):
    # It would pass against `pass`, and go on saying nothing for the rest of
    # the exercise.
    vacuous = parse(
        {
            **copy.deepcopy(SOLVED),
            "examples": [
                {
                    "name": "a_test_that_proves_nothing",
                    "why": "checks the method exists and little else",
                    "code": (
                        "result = Solution().calmest_stretch([4, 9, 1, 2], 2)\n"
                        "assert result is None or result >= 0"
                    ),
                },
                *SOLVED["examples"][1:],
            ],
        }
    )

    with pytest.raises(ScaffoldError, match="assert nothing"):
        build_and_prove(vacuous, "tidal_ledger", "sessions", tmp_path)


# -- installing -------------------------------------------------------------


def test_installing_puts_the_package_where_the_tests_expect_it(kata, tmp_path):
    source = write_package(kata, tmp_path / "work", "tidal_ledger", "sessions", solved=False)
    destination = tmp_path / "repo" / "sessions" / "tidal_ledger"

    install(source, destination)

    assert (destination / "main.py").exists()
    assert (destination.parent / "__init__.py").exists()


def test_an_existing_exercise_is_never_overwritten(kata, tmp_path):
    source = write_package(kata, tmp_path / "work", "tidal_ledger", "sessions", solved=False)
    destination: Path = tmp_path / "repo" / "sessions" / "tidal_ledger"
    destination.mkdir(parents=True)

    with pytest.raises(ScaffoldError, match="already has an exercise"):
        install(source, destination)
