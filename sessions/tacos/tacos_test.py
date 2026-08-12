# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only

"""Scoring the Water Pump — the examples from the brief, and how it has to scale."""

import random

import pytest

from remotemobprogramming.bench import assert_scales_like

from sessions.tacos.main import Solution

SIZES = [2000, 10000, 40000, 100000, 200000]

def build(n: int, rng: random.Random) -> tuple:
    level = 500
    readings: list[int] = []
    for _ in range(n):
        level += rng.randint(-4, 4)
        if level < 0:
            level = -level
        if level > 1000:
            level = 2000 - level
        readings.append(level)
    return (readings, 120)

def test_village_example():
    """The four readings from the story give a score of seven."""
    assert Solution().count_steady_stretches([30, 50, 40, 80], 20) == 7

def test_no_readings_score_zero():
    """With nothing recorded, there is nothing to count."""
    assert Solution().count_steady_stretches([], 20) == 0

def test_gap_itself_is_allowed():
    """A difference exactly equal to allowed_gap is still steady; one less is not."""
    sol = Solution()
    assert sol.count_steady_stretches([10, 1, 10, 1, 10], 9) == 15
    assert sol.count_steady_stretches([10, 1, 10, 1, 10], 8) == 5

def test_steadily_rising_level():
    """When the level climbs by one each minute, runs stop growing at the right length."""
    assert Solution().count_steady_stretches([100, 101, 102, 103, 104], 2) == 12

def test_no_movement_allowed():
    """With a gap of zero, only runs of equal readings count."""
    assert Solution().count_steady_stretches([7, 7, 3, 7], 0) == 5

@pytest.mark.complexity
def test_it_scales():
    """The obvious answer is too slow. This is what says so."""
    assert_scales_like(
        Solution().count_steady_stretches,
        build=build,
        sizes=SIZES,
        expected='n',
        beats='n^2',
    )
