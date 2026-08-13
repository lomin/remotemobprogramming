# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""The scaling harness.

Timing is the one thing these tests never do. A test that measured real work
would be slow and would fail on a loaded machine -- which is exactly the failure
mode the harness exists to avoid, so it would be a poor way to check it. The
clock is injected instead, and the cost of a call is a formula, which makes
every question here deterministic.

So is the place the measurement is made, for the same reason. A clock that only
moves when the work says it does cannot cross a process boundary, so the tests
about fitting and judging measure in this process and say so; the two at the
bottom that really do start a child are the ones that prove the boundary works.
"""

from __future__ import annotations

import math
import os
import random as random_module
import time
from io import StringIO
from itertools import cycle

import pytest

from remotemobprogramming.bench import (
    MODELS,
    QUIET,
    BenchConfigError,
    TooSlow,
    assert_scales_like,
    best_fit_up_to,
    fit_model,
    judge,
    measure,
    measure_here,
    measure_in_child,
    terminal_watch,
)

SIZES = [1_000, 4_000, 16_000, 64_000, 256_000]
OVERHEAD = 5e-5  # a call plus the clock
FIRST = 3e-4  # what the smallest size costs, whatever the class


def scale_for(label: str, sizes=SIZES, *, first: float = FIRST) -> float:
    """Pick a per-operation cost so every class starts from the same time.

    Curves that all begin at the same point are the honest comparison: they
    differ only in how they grow, which is the only thing the fit reads.
    """
    return (first - OVERHEAD) / MODELS[label](sizes[0])


def synthetic(label: str, sizes=SIZES, *, first: float = FIRST):
    """Timings a machine would produce for an implementation of that class."""
    scale = scale_for(label, sizes, first=first)
    return [OVERHEAD + scale * MODELS[label](n) for n in sizes]


class Clock:
    """A fake `perf_counter` that only moves when the work says it does."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def cheap_run(label: str, clock: Clock, *, first: float = FIRST):
    """A `run` that charges the clock what an implementation of `label` would."""
    scale = scale_for(label, first=first)

    def run(n: int) -> None:
        clock.now += OVERHEAD + scale * MODELS[label](n)

    return run


def build(n: int, rng) -> tuple[int, ...]:
    return (n,)


# Sent to a child process by the tests at the bottom, so both of these have to
# be reachable by name. A closure would not survive the trip -- which is the
# point of `test_a_solution_that_cannot_be_sent_to_a_child_says_so_plainly`.


def build_list(n: int, rng: random_module.Random) -> tuple[list[int]]:
    return ([rng.randrange(1_000_000) for _ in range(n)],)


def one_pass(values: list[int]) -> int:
    best = running = 0
    for value in values:
        running = running + value if value % 2 else 0
        best = max(best, running)
    return best


def never_finishes(values: list[int]) -> None:
    while True:
        pass


def explodes(values: list[int]) -> None:
    raise ValueError("the mob's own bug")


def walks_out(values: list[int]) -> None:
    os._exit(3)


# -- fitting ----------------------------------------------------------------


def test_a_model_fits_data_of_its_own_shape_exactly():
    fit = fit_model("n log n", SIZES, synthetic("n log n"))

    assert fit.rms < 1e-9


def test_the_fit_recovers_the_constant_overhead():
    # The intercept is what absorbs call overhead, and without it the small
    # sizes would drag every exponent down.
    fit = fit_model("n", SIZES, synthetic("n"))

    assert fit.intercept == pytest.approx(OVERHEAD, rel=1e-6)


def test_a_quadratic_model_cannot_describe_linear_data():
    fit = fit_model("n^2", SIZES, synthetic("n"))

    assert fit.rms > 0.5


def test_a_model_running_against_the_data_is_not_a_fit():
    # Times that shrink as n grows produce a negative slope. The residual can
    # still come out small, so `usable` is what rules it out, not `rms`.
    falling = [1.0 / n for n in SIZES]

    assert not fit_model("n^2", SIZES, falling).usable


def test_the_verdict_is_taken_from_the_cheapest_model_that_fits():
    fit = best_fit_up_to("n^2", SIZES, synthetic("n"))

    assert fit.label == "n"


def test_a_dearer_model_is_never_considered():
    assert best_fit_up_to("n", SIZES, synthetic("n^2")).label == "n"


# -- the verdict ------------------------------------------------------------


def test_an_implementation_of_the_intended_class_passes():
    verdict = judge(SIZES, synthetic("n log n"), expected="n log n", beats="n^2")

    assert verdict.ok


def test_the_brute_force_class_fails():
    verdict = judge(SIZES, synthetic("n^2"), expected="n log n", beats="n^2")

    assert not verdict.ok


def test_beating_the_intended_class_is_a_pass_not_a_surprise():
    verdict = judge(SIZES, synthetic("n"), expected="n log n", beats="n^2")

    assert verdict.ok
    assert verdict.achieved.label == "n"


def test_something_between_the_two_classes_is_accepted():
    # The honest limit of the method, written down as a test. Timing cannot
    # argue about the range between the intended class and the brute-force one,
    # so a solution that lands in it passes -- failing it would mean failing
    # correct linear solutions too, whose curves bend upwards at a million
    # items for reasons that have nothing to do with the algorithm.
    verdict = judge(SIZES, synthetic("n sqrt n"), expected="n log n", beats="n^2")

    assert verdict.ok
    assert verdict.achieved.label == "n sqrt n"


def test_an_exponential_brute_force_counts_as_separated():
    # 2^n overflows at these sizes, so it cannot be fitted at all -- which is
    # the strongest available evidence that the data is not that shape.
    verdict = judge(SIZES, synthetic("n"), expected="n", beats="2^n")

    assert not verdict.rejected.usable
    assert verdict.ok


def test_noise_within_a_few_percent_does_not_flip_the_verdict():
    times = synthetic("n log n")
    jittered = [t * (1 + 0.04 * math.sin(index * 2.7)) for index, t in enumerate(times)]

    assert judge(SIZES, jittered, expected="n log n", beats="n^2").ok


def test_the_report_shows_every_measurement():
    verdict = judge(SIZES, synthetic("n^2"), expected="n log n", beats="n^2")
    report = verdict.report()

    assert all(f"{n:,}" in report for n in SIZES)
    assert "O(n^2)" in report


# -- the measurement protocol -----------------------------------------------


def test_the_warm_up_round_is_thrown_away():
    clock = Clock()
    seen: list[int] = []

    def run(n: int) -> None:
        first = n not in seen
        seen.append(n)
        # An implausibly cheap first visit: if the warm-up round counted, it
        # would win the min and show up in the result.
        clock.now += 1e-4 * (0.5 if first else 1.0)

    times = measure(run, build, SIZES, rounds=3, timer=clock)

    assert times == pytest.approx([1e-4] * len(SIZES))


def test_each_size_keeps_its_best_round():
    clock = Clock()
    costs = cycle([9e-4, 2e-4, 5e-4])

    def run(n: int) -> None:
        clock.now += next(costs)

    times = measure(run, build, SIZES[:4], rounds=5, timer=clock)

    assert min(times) == pytest.approx(2e-4)


def test_the_sizes_are_visited_round_robin_with_alternating_direction():
    # Finishing all rounds of one size before starting the next would let a
    # machine that warms up over the run penalise whichever size came last.
    clock = Clock()
    seen: list[int] = []

    def run(n: int) -> None:
        seen.append(n)
        clock.now += 1e-4

    measure(run, build, SIZES, rounds=2, timer=clock)

    rounds = [seen[i : i + len(SIZES)] for i in range(0, len(seen), len(SIZES))]
    # The climb comes first and is always ascending; the recorded rounds then
    # alternate.
    assert rounds == [SIZES, SIZES, SIZES[::-1], SIZES]


def test_the_input_is_rebuilt_before_every_call():
    # A solution that works in place would otherwise get its own leftovers.
    clock = Clock()
    built = 0

    def counting_build(n: int, rng) -> tuple[int]:
        nonlocal built
        built += 1
        return (n,)

    def run(n: int) -> None:
        clock.now += 1e-4

    measure(run, counting_build, SIZES, rounds=2, timer=clock)

    assert built == len(SIZES) * 4  # the climb, the warm-up, and two rounds


@pytest.mark.parametrize(
    ("sizes", "complaint"),
    [
        ([100, 200, 400], "at least 4"),
        ([100, 400, 200, 1600, 6400], "strictly increasing"),
        ([100, 200, 400, 800, 1600], "1.5 decades"),
    ],
)
def test_a_measurement_that_cannot_produce_a_verdict_is_refused(sizes, complaint):
    clock = Clock()

    with pytest.raises(BenchConfigError, match=complaint):
        measure(cheap_run("n", clock), build, sizes, timer=clock)


# -- the assertion ----------------------------------------------------------


def test_a_solution_of_the_intended_class_is_accepted():
    clock = Clock()

    assert_scales_like(
        cheap_run("n log n", clock),
        build=build,
        sizes=SIZES,
        expected="n log n",
        beats="n^2",
        timer=clock,
        measure_with=measure_here,
    )


def test_a_brute_force_solution_is_rejected_with_the_numbers():
    clock = Clock()

    with pytest.raises(AssertionError) as caught:
        assert_scales_like(
            cheap_run("n^2", clock),
            build=build,
            sizes=SIZES,
            expected="n log n",
            beats="n^2",
            budget=1e9,  # let it finish, so the fit is what rejects it
            timer=clock,
            measure_with=measure_here,
        )

    assert "does not scale like O(n log n)" in str(caught.value)
    assert "256,000" in str(caught.value)


def test_a_solution_that_would_run_for_hours_fails_instead_of_running_for_hours():
    # Without the budget this test does not reject a quadratic answer to a
    # linear problem at all -- it sits at the top of the ladder until someone
    # gives up, which is worse than a red test in every way.
    clock = Clock()

    with pytest.raises(AssertionError):
        assert_scales_like(
            cheap_run("n^2", clock),
            build=build,
            sizes=SIZES,
            expected="n log n",
            beats="n^2",
            timer=clock,
            measure_with=measure_here,
        )

    spent_at_the_top = MODELS["n^2"](SIZES[-1]) / MODELS["n^2"](SIZES[0]) * FIRST
    assert clock.now < spent_at_the_top, "it climbed higher than the budget allows"


def test_something_hopelessly_slow_gives_up_rather_than_fitting_two_points():
    clock = Clock()

    def glacial(n: int) -> None:
        clock.now += 1e-3 * 1000 ** (n / SIZES[0])

    with pytest.raises(TooSlow) as caught:
        assert_scales_like(
            glacial,
            build=build,
            sizes=SIZES,
            expected="n",
            beats="n^2",
            timer=clock,
            measure_with=measure_here,
        )

    assert "never got far enough up the ladder" in str(caught.value)
    assert "never reached" in str(caught.value)


def test_the_budget_stretches_for_a_slower_machine():
    # The measurement is only portable if the allowance is too: the same
    # implementation must not fail merely for running on older hardware.
    fast, slow = Clock(), Clock()

    def machine(clock, cost):
        def run(n: int) -> None:
            clock.now += cost * MODELS["n"](n) / MODELS["n"](SIZES[0])

        return run

    assert_scales_like(
        machine(fast, 3e-4),
        build=build,
        sizes=SIZES,
        expected="n",
        beats="n^2",
        timer=fast,
        measure_with=measure_here,
    )
    # Ten times slower at every size, and still measured rather than refused.
    assert_scales_like(
        machine(slow, 3e-3),
        build=build,
        sizes=SIZES,
        expected="n",
        beats="n^2",
        budget=200.0,
        timer=slow,
        measure_with=measure_here,
    )


def test_classes_too_close_to_separate_are_refused_rather_than_guessed_at():
    clock = Clock()

    with pytest.raises(BenchConfigError, match="too close"):
        assert_scales_like(
            cheap_run("n", clock),
            build=build,
            sizes=SIZES,
            expected="n",
            beats="n log n",
            timer=clock,
            measure_with=measure_here,
        )


def test_an_unknown_complexity_is_refused():
    clock = Clock()

    with pytest.raises(BenchConfigError, match="unknown complexity"):
        assert_scales_like(
            cheap_run("n", clock),
            build=build,
            sizes=SIZES,
            expected="linearithmic",
            beats="n^2",
            timer=clock,
            measure_with=measure_here,
        )


def test_the_premise_holds_against_a_real_clock():
    """The one test here that actually measures something.

    Everything above assumes a fit on clean numbers says something about real
    code. This checks that assumption on real hardware, where cache effects
    make a genuinely linear pass measure a little steeper than linear. Linear
    against quadratic is the widest gap the harness ever has to judge, so a
    loaded machine has a lot of room before this could flip.

    It is also the one test that runs the whole thing as the mob does: a real
    clock, a real child process, and a solution sent to it by name. `one_pass`
    and `build_list` are at the top of this file rather than inside here for
    exactly that reason -- a function defined inside another cannot be sent to
    a child, which is the one shape a scaffolded exercise never has.
    """
    assert_scales_like(
        one_pass,
        build=build_list,
        sizes=[8_000, 32_000, 128_000, 512_000],
        expected="n",
        beats="n^2",
        rounds=3,
    )


def test_sizes_too_small_to_measure_are_refused():
    # Below a few hundred microseconds the fit describes the harness, not the
    # algorithm, so this has to be a setup error and not a failed assertion.
    clock = Clock()

    with pytest.raises(BenchConfigError, match="call overhead"):
        assert_scales_like(
            cheap_run("n", clock, first=6e-5),
            build=build,
            sizes=SIZES,
            expected="n",
            beats="n^2",
            timer=clock,
            measure_with=measure_here,
        )


# -- the deadline -----------------------------------------------------------
#
# The measurement is made in a child process for one reason: so that a call
# which never comes back can be stopped rather than waited for. These are the
# tests that really start one, so they are the slow ones in this file -- a
# second or two each, against microseconds everywhere above.

LADDER = [1_000, 4_000, 16_000, 64_000]


def measurement(run, **overrides):
    """`measure_in_child` with a short deadline, so a hang costs a second."""
    settings = dict(seed=1, rounds=1, budget=1.0, limit=1.0)
    return measure_in_child(run, build_list, LADDER, **(settings | overrides))


def test_a_call_that_never_comes_back_is_killed_rather_than_waited_for():
    started = time.perf_counter()

    with pytest.raises(TooSlow):
        measurement(never_finishes, watch=lambda message: None)

    # The deadline is a second, so anything near it is the deadline working and
    # anything far above it is the harness waiting for something it cannot stop.
    assert time.perf_counter() - started < 10.0


def test_the_report_names_the_size_that_never_came_back():
    with pytest.raises(TooSlow) as caught:
        measurement(never_finishes, watch=lambda message: None)

    assert "never came back" in str(caught.value)
    assert f"{LADDER[0]:,}" in str(caught.value)


def test_a_measurement_that_dies_without_a_word_is_reported_not_hung():
    # The operating system stepping in -- out of memory, most often. Before the
    # child existed this looked exactly like a hang, because it was one.
    with pytest.raises(TooSlow) as caught:
        measurement(walks_out, watch=lambda message: None)

    assert "without a word" in str(caught.value)
    assert "exit code 3" in str(caught.value)


def test_an_error_in_the_solution_still_reads_like_a_test_failure():
    # The solution throwing is the mob's own bug and has to arrive as itself,
    # not as a harness error about a child process.
    with pytest.raises(ValueError, match="the mob's own bug") as caught:
        measurement(explodes, watch=lambda message: None)

    assert any("explodes" in note for note in caught.value.__notes__)


def test_a_solution_that_cannot_be_sent_to_a_child_says_so_plainly():
    def closure(values: list[int]) -> None:
        """Defined in here, so it cannot be reached by name from anywhere else."""

    with pytest.raises(BenchConfigError, match="reachable by name"):
        measurement(closure, watch=lambda message: None)


# -- saying what is taking the time -----------------------------------------


def test_every_call_is_announced_before_it_is_made():
    clock = Clock()
    said: list[tuple] = []

    measure(cheap_run("n", clock), build, SIZES, rounds=2, timer=clock, announce=said.append)

    # Every call is announced, then reported, and never the other way round.
    assert all(kind in ("call", "done") for kind, *_ in said)
    assert [kind for kind, *_ in said] == ["call", "done"] * (len(said) // 2)
    phases = {message[2] for message in said if message[0] == "call"}
    assert phases == {"finding the ladder", "warming up", "round 1 of 2", "round 2 of 2"}


def test_the_progress_line_names_the_size_and_what_it_is_doing():
    written = StringIO()

    watch = terminal_watch(terminal=written, quiet_for=0.0, timer=Clock())
    watch(("call", 40_000, "round 2 of 3"))
    drawn = written.getvalue()
    watch(("stop",))

    assert "40,000" in drawn
    assert "round 2 of 3" in drawn


def test_nothing_is_drawn_before_the_measurement_has_run_for_a_moment():
    # A solution that walks the ladder quickly should not flash a spinner at
    # the mob on its way past.
    written = StringIO()

    watch = terminal_watch(terminal=written, quiet_for=1.0, timer=Clock())
    watch(("call", 1_000, "finding the ladder"))
    drawn = written.getvalue()
    watch(("stop",))

    assert drawn == ""


def test_a_measurement_with_no_terminal_to_draw_on_says_nothing(monkeypatch):
    # Under the generation gates, and in any run whose output is a pipe. Escape
    # codes in a log file are worse than silence, and a missing terminal is not
    # a reason to fail a measurement.
    monkeypatch.setenv(QUIET, "1")
    watch = terminal_watch()

    assert watch(("call", 1_000, "finding the ladder")) is None
    assert watch(("stop",)) is None
