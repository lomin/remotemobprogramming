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

A fit needs the calls to come back. The climb below catches an answer that is
merely too slow, but it weighs the allowance *between* calls, and the call that
never returns never reaches the weighing -- so the mob gets no verdict at all,
just a terminal that has stopped. That is worse than a red test in every way,
and it is the one failure a test about slowness must not have.

So the measurement is made in a child process and this one watches it. Python
cannot stop a thread, and an answer that does not terminate has to be
answerable anyway, so the only honest way to put a deadline on a call is to put
it somewhere that can be killed. The child narrates each call before it makes
it; silence for longer than the deadline is the verdict.

It costs an interpreter start -- about seventy milliseconds, once per
measurement, outside every timed region -- and it moves the solution into a
fresh interpreter, so anything it had cached on itself while the worked
examples ran is gone. That second one is a gain: the scaling test now measures
the algorithm from cold, which is what it always claimed to be measuring.
"""

from __future__ import annotations

import gc
import math
import os
import random
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from multiprocessing import get_context
from time import perf_counter
from typing import NoReturn

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
# Set by the generation gates, which run this inside a subprocess while their
# own spinner is on the terminal. Two live displays on one terminal fight.
QUIET = "MOB_BENCH_QUIET"
# The terminal itself, opened by name. Nothing else gets past pytest's capture.
TERMINAL = "CONOUT$" if os.name == "nt" else "/dev/tty"
# How long the measurement runs before it is worth saying anything about. A
# correct solution walks the whole ladder in about this, and a spinner that
# flashes for a moment is worse than no spinner.
QUIET_FOR = 1.0


# What the measurement says about itself as it goes, and where that goes. The
# child sends these down a pipe; in this process the default is to say nothing.
Message = tuple
Announce = Callable[[Message], None]
Watch = Callable[[Message], None]


def _quiet(message: Message) -> None:
    """Not being listened to costs the measurement nothing."""


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
    announce: Announce = _quiet,
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

    `announce` is told the size about to be run and then the time it took. It is
    what lets whoever is waiting put a deadline on a call and say out loud what
    is taking the minute, and it is called outside every timed region so it
    cannot show up in a number.
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

    reachable = _climb(run, build, sizes, budget / (rounds + 1), seed, timer, announce)
    if len(reachable) < 4:
        raise TooSlow(
            _too_slow_report(sizes, reachable, budget),
        )

    best = [math.inf] * len(reachable)
    for round_index in range(rounds + 1):  # +1 for the discarded warm-up
        phase = "warming up" if round_index == 0 else f"round {round_index} of {rounds}"
        order = range(len(reachable))
        if round_index % 2:
            order = reversed(order)
        for index in order:
            rng = random.Random(seed + round_index)
            size = reachable[index][0]
            args = build(size, rng)
            announce(("call", size, phase))
            gc.collect()
            gc.disable()
            try:
                started = timer()
                run(*args)
                elapsed = timer() - started
            finally:
                gc.enable()
            announce(("done", size, elapsed))
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
    announce: Announce = _quiet,
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
        announce(("call", size, "finding the ladder"))
        gc.collect()
        gc.disable()
        try:
            started = timer()
            run(*args)
            elapsed = timer() - started
        finally:
            gc.enable()
        announce(("done", size, elapsed))
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


# -- running it somewhere it can be stopped ---------------------------------


Measurement = Callable[..., list[float]]


def measure_here(
    run: Callable[..., object],
    build: Callable[[int, random.Random], tuple],
    sizes: Sequence[int],
    *,
    seed: int,
    rounds: int,
    budget: float,
    limit: float,
    timer: Callable[[], float],
    watch: Watch | None = None,
) -> list[float]:
    """Measure in this process, where nothing can be stopped.

    No deadline is possible here -- that is the whole reason for the child --
    so `limit` is accepted and ignored, and so is `watch`, since there is
    nothing to watch for. This exists for the harness's own tests, which inject
    a clock that only moves when the work says it does and therefore cannot
    cross a process boundary.
    """
    return measure(run, build, sizes, seed=seed, rounds=rounds, budget=budget, timer=timer)


def _measure_in_child(conn, run, build, sizes, seed, rounds, budget) -> None:
    """The measurement, narrating itself so the process above can time it out.

    Everything that comes back goes down the pipe rather than up a stack, the
    failures included: the parent is a different process and has no other way
    to hear about them.
    """
    try:
        times = measure(
            run, build, sizes, seed=seed, rounds=rounds, budget=budget, announce=conn.send
        )
        conn.send(("times", times))
    except BaseException as error:  # noqa: BLE001 -- reported to the parent, not handled
        report = traceback.format_exc()
        try:
            conn.send(("raised", error, report))
        except Exception:
            # Not every exception survives a pipe. The text always does, and
            # the mob needs the text far more than it needs the type.
            conn.send(("raised", None, report))
    finally:
        conn.close()


def measure_in_child(
    run: Callable[..., object],
    build: Callable[[int, random.Random], tuple],
    sizes: Sequence[int],
    *,
    seed: int,
    rounds: int,
    budget: float,
    limit: float,
    timer: Callable[[], float] = perf_counter,
    watch: Watch | None = None,
) -> list[float]:
    """Measure where it can be stopped, and stop it if a call does not come back.

    `spawn` rather than `fork`, on every platform: Windows has nothing else,
    3.13 already warns about forking a process that has threads, and one start
    method means one set of behaviour to reason about. The cost is that `run`
    and `build` are sent by name and rebuilt in the child, which a scaffolded
    exercise always survives -- `Solution` and `build` are both module-level by
    construction -- and which anything else has to be told about plainly.

    `limit` is how long one call may be silent for. It is real seconds: the
    injected clock stops at the process boundary, because the question here is
    not how much work a call did but whether it is still going.
    """
    context = get_context("spawn")
    reading, writing = context.Pipe(duplex=False)
    process = context.Process(
        target=_measure_in_child,
        args=(writing, run, build, list(sizes), seed, rounds, budget),
        daemon=True,
    )
    try:
        process.start()
    except (AttributeError, TypeError, ValueError) as error:
        raise BenchConfigError(
            "this could not be sent to the process that measures it, so it cannot "
            f"be timed: {error}. the solution and its `build` both have to be "
            "reachable by name -- defined at the top level of their module, not "
            "inside another function"
        ) from None
    # The parent's copy of the writing end, closed so that the child going away
    # shows up here as an end of file rather than as a wait that never ends.
    writing.close()

    watcher = terminal_watch() if watch is None else watch
    return _listen(reading, process, limit, watcher)


def _listen(reading, process, limit: float, watch: Watch) -> list[float]:
    """Follow the narration, and kill the measurement if it stops narrating."""
    measured: dict[int, float] = {}
    running: int | None = None
    try:
        while True:
            if not reading.poll(limit):
                process.kill()
                process.join()
                raise TooSlow(_never_came_back_report(running, measured, limit))
            try:
                message = reading.recv()
            except EOFError:
                process.join()
                raise TooSlow(_died_report(running, measured, process.exitcode)) from None

            watch(message)
            kind = message[0]
            if kind == "call":
                running = message[1]
            elif kind == "done":
                size, elapsed = message[1], message[2]
                measured[size] = min(elapsed, measured.get(size, math.inf))
            elif kind == "times":
                process.join()
                return list(message[1])
            elif kind == "raised":
                process.join()
                _reraise(message[1], message[2])
    finally:
        watch(("stop",))
        reading.close()
        if process.is_alive():
            process.kill()
            process.join()


def _reraise(error: BaseException | None, report: str) -> NoReturn:
    """Put the child's failure back where the mob expects to find it.

    Our own verdicts already say everything they have to say, so they are
    re-raised bare. Anything else is the solution itself throwing, and the
    frames that led to it are in the child's traceback and nowhere else, so
    they are carried across as a note.
    """
    if error is None:
        raise AssertionError(report)
    if not isinstance(error, TooSlow | BenchConfigError):
        error.add_note(report)
    raise error


def _measurements(measured: dict[int, float]) -> list[str]:
    return [
        f"    {size:>12,}  {elapsed * 1e3:>10.1f}ms" for size, elapsed in sorted(measured.items())
    ]


def _never_came_back_report(running: int | None, measured: dict[int, float], limit: float) -> str:
    where = f"the call at n = {running:,}" if running is not None else "the first call"
    lines = [
        f"{where} never came back. it had the whole {limit:.0f}s to itself and was "
        "still going, so it was stopped. that is not a constant factor and no faster "
        "laptop fixes it: either something in there does not finish, or it grows so "
        "fast that the next rung of the ladder may as well be forever.",
        "",
    ]
    lines += _measurements(measured)
    if running is not None:
        lines.append(f"    {running:>12,}  {'never came back':>12}")
    return "\n".join(lines)


def _died_report(running: int | None, measured: dict[int, float], exitcode: int | None) -> str:
    where = f" while it was at n = {running:,}" if running is not None else ""
    lines = [
        f"the measurement stopped without a word{where} (exit code {exitcode}). "
        "nothing in the harness ends that way, so this was ended from outside -- "
        "which on a machine that has just been asked for a great deal of memory at "
        "once is the operating system stepping in, and is as much a verdict about "
        "the solution as a slow clock would be.",
        "",
    ]
    return "\n".join(lines + _measurements(measured))


# -- saying what is taking the time -----------------------------------------


def terminal_watch(
    *,
    terminal=None,
    quiet_for: float = QUIET_FOR,
    timer: Callable[[], float] = perf_counter,
) -> Watch:
    """A live line on the terminal, or silence when there is nowhere to draw.

    The scaling test is the longest the mob ever waits on this tool, and until
    now it waited in silence -- `Ui.step` says the same thing one layer up, and
    for the same reason: a terminal with nothing on it looks exactly like one
    waiting for you to press enter.

    Getting a word out is harder here than it looks. pytest captures at the
    file-descriptor level, so `print` and even `sys.__stderr__` are held back
    until the test has finished, which is precisely too late. What capture
    cannot reach is the terminal opened by its own name, so that is what this
    does -- and where there is no terminal to open, which is any run whose
    output is a pipe, it says nothing at all rather than posting escape codes
    into somebody's log.
    """
    if os.environ.get(QUIET):
        return _quiet
    if terminal is None:
        try:
            terminal = open(TERMINAL, "w", buffering=1, encoding="utf-8")  # noqa: SIM115
        except OSError:
            return _quiet
    return _Spinner(terminal, quiet_for=quiet_for, timer=timer)


class _Spinner:
    """One line, redrawn, saying which size is being measured and for how long."""

    def __init__(self, terminal, *, quiet_for: float, timer: Callable[[], float]) -> None:
        # Imported here rather than at the top of the module: this is the only
        # thing in the file that needs a terminal library, and the child that
        # does the measuring must not pay to import one.
        from rich.console import Console
        from rich.status import Status

        self.terminal = terminal
        self.timer = timer
        self.quiet_for = quiet_for
        self.started = timer()
        self.console = Console(file=terminal, force_terminal=True)
        self.status: Status | None = None
        self._new_status = Status

    def __call__(self, message: Message) -> None:
        kind = message[0]
        if kind == "call":
            self._say(f"{message[2]}, n = {message[1]:,}")
        elif kind in ("stop", "times", "raised"):
            self.close()

    def _say(self, what: str) -> None:
        from .render import duration

        elapsed = self.timer() - self.started
        if elapsed < self.quiet_for:
            return
        text = f"[dim]measuring how it scales — {what}  ({duration(elapsed)})[/dim]"
        if self.status is None:
            self.status = self._new_status(text, spinner="dots", console=self.console)
            self.status.start()
        # Handing the spinner back in is what forces the redraw; `update` alone
        # waits for the next scheduled refresh, and the line has to be on the
        # screen before the call it describes starts, not a tick later.
        self.status.update(text, spinner="dots")

    def close(self) -> None:
        if self.status is not None:
            self.status.stop()
            self.status = None
        if not self.terminal.closed:
            self.terminal.close()


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
    measure_with: Measurement = measure_in_child,
) -> None:
    """Fail unless the implementation scales at worst like `expected`.

    `run` is called as `run(*build(n, rng))`. `beats` is the complexity of the
    obvious brute-force answer; the whole point of the test is that the fit
    tells the two apart.

    `budget` is in seconds on the machine this was calibrated on, and is scaled
    by a quick measurement of the machine actually running it, so a slower one
    is given proportionally longer instead of failing correct work. The same
    number, whole, is how long any one call may go quiet for before it is
    stopped -- four times what the climb is allowed to spend, deliberately, so
    that the deadline can only ever fire for code that does not come back and
    never for code that is merely dear. Judging slowness is the climb's job,
    and it does it with the number the call actually produced.
    """
    for label in (expected, beats):
        if label not in MODELS:
            raise BenchConfigError(f"unknown complexity {label!r}; known: {', '.join(MODELS)}")
    if ORDER[beats] - ORDER[expected] < MIN_GAP:
        raise BenchConfigError(
            f"O({expected}) and O({beats}) are too close to separate by timing; "
            f"they need to be at least {MIN_GAP} steps apart"
        )

    allowed = budget * machine_factor(timer)
    times = measure_with(
        run,
        build,
        sizes,
        seed=seed,
        rounds=rounds,
        budget=allowed,
        limit=allowed,
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
