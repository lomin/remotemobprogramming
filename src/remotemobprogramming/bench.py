# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Measuring how an implementation scales, and deciding whether that is good enough.

A complexity test cannot assert a wall-clock budget: the number that comes out
of the clock belongs to the machine, not to the algorithm, so a frozen budget
turns red when the mob hands over to someone with an older laptop. What *is* a
property of the algorithm is the shape of the curve. A slower machine multiplies
every point by roughly the same constant, and a constant factor is exactly what
a curve fit is free to absorb.

So the measurement is redone from scratch on every run and the verdict comes
from the fit. What the fit can and cannot settle is worth being precise about:

- It separates classes that differ by a polynomial degree easily. Over three
  decades O(n log n) sits at an exponent near 1.1 and O(n^2) at 2.0.
- It cannot separate adjacent classes. O(n) also sits near 1.0-1.1, and the
  gap is smaller than the systematic error from cache effects alone -- a
  genuinely linear pass over a few million items measures steeper than linear
  once the data stops fitting in L3.

That is why the assertion is never "this is exactly O(n log n)". It is "this is
at worst the intended class, and decisively better than the brute force one",
which only ever asks the fit to separate classes a full degree apart.
"""

from __future__ import annotations

import gc
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

# Growth functions, ordered from cheapest to dearest. The order is what lets
# "you found something faster than the target" count as a pass.
MODELS: dict[str, Callable[[int], float]] = {
    "1": lambda n: 1.0,
    "log n": lambda n: math.log2(n),
    "n": lambda n: float(n),
    "n log n": lambda n: n * math.log2(n),
    "n sqrt n": lambda n: n * math.sqrt(n),
    "n^2": lambda n: float(n) ** 2,
    "n^2 log n": lambda n: float(n) ** 2 * math.log2(n),
    "n^3": lambda n: float(n) ** 3,
    "2^n": lambda n: math.inf if n > 60 else float(2**n),
}
ORDER = {label: index for index, label in enumerate(MODELS)}

# Two classes closer than this cannot be told apart by timing, so a problem
# whose brute force is only one step dearer than its intended solution is not
# testable this way and is rejected at generation time.
MIN_GAP = 2

DEFAULT_SEED = 20260812
DEFAULT_ROUNDS = 3
# Wall clock the measurement is allowed, in seconds on the machine this was
# calibrated on. A correct solution needs a couple of seconds for a ladder up
# to a million, so this is roughly ten times over.
DEFAULT_BUDGET = 20.0
# A pure-Python loop of this length took REFERENCE_SECONDS where the budget was
# chosen. Timing it takes a few milliseconds and turns the budget from "twenty
# seconds" into "twenty seconds' worth of work", so a slower laptop gets
# proportionally longer rather than failing a correct solution.
REFERENCE_ITERATIONS = 300_000
REFERENCE_SECONDS = 7.7e-3
# Relative RMS the data has to achieve under some model cheaper than the brute
# force one. Generous on purpose: a genuinely linear pass over a million items
# measures around 20% away from linear once the working set leaves L3, and
# failing correct code is a far worse outcome here than passing slack code.
DEFAULT_TOLERANCE = 0.35
# How much worse the brute-force model has to fit, in absolute relative-RMS.
# A ratio does not work: relative RMS saturates around 50-60% for a badly wrong
# model, because the intercept and slope can always chase the largest points,
# so "three times worse" becomes unreachable exactly when the honest residual
# is large.
DEFAULT_SEPARATION = 0.15
# Below this a single call is mostly clock and call overhead, and the fit
# measures the harness rather than the algorithm.
MIN_MEASURABLE_SECONDS = 1e-4


def machine_factor(timer: Callable[[], float] = perf_counter) -> float:
    """How much slower this machine is than the one the budget was set on.

    Without this the budget is a statement about hardware rather than about the
    algorithm, and the whole point of fitting a curve instead of asserting a
    deadline was to stop hardware having a vote.
    """
    gc.collect()
    gc.disable()
    try:
        started = timer()
        total = 0
        for index in range(REFERENCE_ITERATIONS):
            total += index
        elapsed = timer() - started
    finally:
        gc.enable()
    return max(elapsed / REFERENCE_SECONDS, 0.1)


class TooSlow(AssertionError):
    """The implementation could not be measured because it never finished.

    An AssertionError, because this is a verdict about the solution and not a
    fault in the harness: an answer that cannot get through the smallest sizes
    in the time the intended one needs for all of them has already lost.
    """


class BenchConfigError(Exception):
    """The measurement was set up in a way that cannot produce a verdict.

    Deliberately not an AssertionError: this is the scaffolding being wrong,
    not the solution being wrong, and the two must not look alike.
    """


@dataclass(frozen=True)
class Fit:
    """A least-squares fit of `time ~ a + b * model(n)`."""

    label: str
    intercept: float
    slope: float
    rms: float  # relative RMS residual: 0.05 means the model tracks within ~5%

    @property
    def usable(self) -> bool:
        # A negative slope means the model runs the wrong way against the data,
        # which is not a fit at all however small the residual looks.
        return self.slope >= 0 and math.isfinite(self.rms)


def fit_model(label: str, sizes: Sequence[int], times: Sequence[float]) -> Fit:
    """Weighted least squares of `t = a + b * f(n)`.

    Weighted by 1/t^2, which minimises *relative* error. Unweighted, the two
    largest sizes would decide the fit on their own and a 30% miss at the small
    end would go unnoticed.
    """
    growth = MODELS[label]
    points = [(growth(n), t) for n, t in zip(sizes, times, strict=True)]
    if any(not math.isfinite(f) for f, _ in points):
        return Fit(label, 0.0, 0.0, math.inf)

    weights = [1.0 / (t * t) for _, t in points]
    s0 = sum(weights)
    s1 = sum(w * f for w, (f, _) in zip(weights, points, strict=True))
    s2 = sum(w * f * f for w, (f, _) in zip(weights, points, strict=True))
    t0 = sum(w * t for w, (_, t) in zip(weights, points, strict=True))
    t1 = sum(w * f * t for w, (f, t) in zip(weights, points, strict=True))

    denominator = s0 * s2 - s1 * s1
    if denominator == 0:
        return Fit(label, 0.0, 0.0, math.inf)

    slope = (s0 * t1 - s1 * t0) / denominator
    intercept = (t0 - slope * s1) / s0
    errors = [((intercept + slope * f) - t) / t for f, t in points]
    rms = math.sqrt(sum(e * e for e in errors) / len(errors))
    return Fit(label, intercept, slope, rms)


def best_fit_up_to(label: str, sizes: Sequence[int], times: Sequence[float]) -> Fit:
    """The best-fitting model no dearer than `label`.

    A solution that scales *better* than the target is a better solution, so the
    verdict is taken from whichever cheap model actually describes the data.
    """
    candidates = [fit_model(name, sizes, times) for name in MODELS if ORDER[name] <= ORDER[label]]
    usable = [fit for fit in candidates if fit.usable]
    return min(usable or candidates, key=lambda fit: fit.rms)


def best_fit_below(label: str, sizes: Sequence[int], times: Sequence[float]) -> Fit:
    """The best-fitting model strictly cheaper than `label`.

    This is what the verdict is actually taken from, and the choice deserves
    saying out loud: the claim being tested is "not the brute-force class", not
    "exactly the intended class". Real memory behaviour bends a linear curve
    upwards at a million items, so insisting the data fit O(n) and nothing
    dearer would fail correct solutions on the machines with the smallest
    caches. Everything between the intended class and the brute-force one is
    accepted, which is precisely the range timing cannot argue about.
    """
    cheaper = [name for name in MODELS if ORDER[name] < ORDER[label]]
    candidates = [fit_model(name, sizes, times) for name in cheaper]
    usable = [fit for fit in candidates if fit.usable]
    return min(usable or candidates, key=lambda fit: fit.rms)


def measure(
    run: Callable[..., object],
    build: Callable[[int, random.Random], tuple],
    sizes: Sequence[int],
    *,
    seed: int = DEFAULT_SEED,
    rounds: int = DEFAULT_ROUNDS,
    budget: float = DEFAULT_BUDGET,
    timer: Callable[[], float] = perf_counter,
) -> list[float]:
    """Best-of-`rounds` seconds for each size the implementation can reach.

    `run` is called as `run(*build(n, rng))`, so a solution's method can be
    handed over as-is.

    Four things about the protocol matter more than they look:

    - The ladder is climbed once before anything is recorded, and abandoned if
      it runs out of budget. That pass is both the warm-up and the safety
      valve: without it, a quadratic answer to a linear problem does not fail
      this test, it runs for hours at the top of the ladder.
    - Sizes are then visited round-robin with the direction alternating, rather
      than finishing all rounds of one size before moving on. Thermal drift over
      the run then biases every size the same way instead of penalising
      whichever one happened to be measured last.
    - The first recorded round is thrown away too. CPython's specialising
      interpreter needs a few executions before it settles.
    - The input is rebuilt, untimed, before every single call. Reusing it would
      both warm the caches unrealistically and hand corrupted data to a solution
      that works in place.
    """
    if len(sizes) < 4:
        raise BenchConfigError(f"need at least 4 sizes to fit a curve, got {len(sizes)}")
    if list(sizes) != sorted(set(sizes)):
        raise BenchConfigError("sizes must be strictly increasing and distinct")
    if sizes[-1] / sizes[0] < 30:
        raise BenchConfigError(
            f"sizes span only {sizes[-1] / sizes[0]:.1f}x; under ~1.5 decades the "
            "candidate models are indistinguishable"
        )

    reachable = _climb(run, build, sizes, budget / (rounds + 1), seed, timer)
    if len(reachable) < 4:
        raise TooSlow(
            _too_slow_report(sizes, reachable, budget),
        )

    best = [math.inf] * len(reachable)
    for round_index in range(rounds + 1):  # +1 for the discarded warm-up
        order = range(len(reachable))
        if round_index % 2:
            order = reversed(order)
        for index in order:
            rng = random.Random(seed + round_index)
            args = build(reachable[index][0], rng)
            gc.collect()
            gc.disable()
            try:
                started = timer()
                run(*args)
                elapsed = timer() - started
            finally:
                gc.enable()
            if round_index and elapsed < best[index]:
                best[index] = elapsed
    return best


def _climb(
    run: Callable[..., object],
    build: Callable[[int, random.Random], tuple],
    sizes: Sequence[int],
    allowance: float,
    seed: int,
    timer: Callable[[], float],
) -> list[tuple[int, float]]:
    """One pass up the ladder, stopping when the allowance runs out.

    This doubles as the warm-up and as the safety valve. Without it a solution
    that is quadratic where the intended answer is linear does not fail the
    test -- it runs for hours at the top of the ladder, which is worse than a
    red test in every way.
    """
    reached: list[tuple[int, float]] = []
    spent = 0.0
    rng = random.Random(seed)
    for size in sizes:
        args = build(size, rng)
        gc.collect()
        gc.disable()
        try:
            started = timer()
            run(*args)
            elapsed = timer() - started
        finally:
            gc.enable()
        reached.append((size, elapsed))
        spent += elapsed
        if spent > allowance:
            break
    return reached


def _too_slow_report(
    sizes: Sequence[int], reached: Sequence[tuple[int, float]], budget: float
) -> str:
    lines = [
        "this never got far enough up the ladder to be measured, which is its "
        "own answer: the intended solution walks the whole ladder in a fraction "
        f"of the {budget:.0f}s allowed.",
        "",
    ]
    lines += [f"    {size:>12,}  {elapsed * 1e3:>10.1f}ms" for size, elapsed in reached]
    unreached = [size for size in sizes if size not in {s for s, _ in reached}]
    if unreached:
        listed = ", ".join(f"{size:,}" for size in unreached)
        lines += ["", f"    never reached: {listed}"]
    return "\n".join(lines)


@dataclass(frozen=True)
class Verdict:
    sizes: Sequence[int]
    times: Sequence[float]
    achieved: Fit
    rejected: Fit
    expected: str
    ok: bool

    def report(self) -> str:
        lines = [
            f"    {'n':>12}  {'best':>10}  {'per n':>12}",
            f"    {'-' * 12}  {'-' * 10}  {'-' * 12}",
        ]
        for n, t in zip(self.sizes, self.times, strict=True):
            lines.append(f"    {n:>12,}  {t * 1e3:>9.3f}ms  {t / n * 1e9:>9.1f}ns")
        lines += [
            "",
            f"    aiming for O({self.expected}), measured closest to"
            f" O({self.achieved.label})  (within {self.achieved.rms:.1%})",
            f"    the brute-force O({self.rejected.label}) fits within {self.rejected.rms:.1%}",
        ]
        return "\n".join(lines)


def judge(
    sizes: Sequence[int],
    times: Sequence[float],
    expected: str,
    beats: str,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    separation: float = DEFAULT_SEPARATION,
) -> Verdict:
    achieved = best_fit_below(beats, sizes, times)
    rejected = fit_model(beats, sizes, times)

    tracks = achieved.usable and achieved.rms <= tolerance
    # An unusable fit for the brute-force model is not a technicality -- an
    # exponential model against six-figure inputs overflows, and "no way to fit
    # this" is the strongest possible statement that the data is not that shape.
    separated = (not rejected.usable) or rejected.rms - achieved.rms >= separation
    return Verdict(sizes, times, achieved, rejected, expected, tracks and separated)


def assert_scales_like(
    run: Callable[..., object],
    *,
    build: Callable[[int, random.Random], tuple],
    sizes: Sequence[int],
    expected: str,
    beats: str,
    seed: int = DEFAULT_SEED,
    rounds: int = DEFAULT_ROUNDS,
    budget: float = DEFAULT_BUDGET,
    timer: Callable[[], float] = perf_counter,
) -> None:
    """Fail unless the implementation scales at worst like `expected`.

    `run` is called as `run(*build(n, rng))`. `beats` is the complexity of the
    obvious brute-force answer; the whole point of the test is that the fit
    tells the two apart.

    `budget` is in seconds on the machine this was calibrated on, and is scaled
    by a quick measurement of the machine actually running it, so a slower one
    is given proportionally longer instead of failing correct work.
    """
    for label in (expected, beats):
        if label not in MODELS:
            raise BenchConfigError(f"unknown complexity {label!r}; known: {', '.join(MODELS)}")
    if ORDER[beats] - ORDER[expected] < MIN_GAP:
        raise BenchConfigError(
            f"O({expected}) and O({beats}) are too close to separate by timing; "
            f"they need to be at least {MIN_GAP} steps apart"
        )

    times = measure(
        run,
        build,
        sizes,
        seed=seed,
        rounds=rounds,
        budget=budget * machine_factor(timer),
        timer=timer,
    )
    sizes = sizes[: len(times)]
    if min(times) < MIN_MEASURABLE_SECONDS:
        raise BenchConfigError(
            f"the fastest measurement was {min(times) * 1e6:.0f}us, which is mostly "
            "call overhead — either the method does not do anything yet, or the "
            f"smallest size needs to be larger than {sizes[0]:,}"
        )

    verdict = judge(times=times, sizes=sizes, expected=expected, beats=beats)
    if verdict.ok:
        return

    if verdict.achieved.rms <= DEFAULT_TOLERANCE:
        headline = (
            f"this grows too much like the brute-force O({beats}) to tell the two "
            f"apart, so it is not the O({expected}) answer"
        )
    else:
        headline = (
            f"this does not scale like O({expected}); nothing cheaper than the "
            f"brute-force O({beats}) describes the measurements"
        )
    raise AssertionError(f"{headline}\n\n{verdict.report()}\n")
