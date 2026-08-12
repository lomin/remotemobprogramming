# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""What we ask Claude for, and what we insist on getting back.

The brief is LeetCode's rigour with Advent of Code's framing. LeetCode tells you
"given an integer array nums, return the maximum sum of any subarray of length
k" -- the data structure is the first noun in the sentence, so the technique is
announced before you have read the question. Advent of Code tells you the elves
are recording calorie counts and leaves the modelling to you. That modelling is
most of the skill, and it is exactly what the LeetCode phrasing removes.

So: keep the tiers, keep the canonical algorithms, keep the guarantee that a
better-than-obvious answer exists. Drop the vocabulary.

Both vocabularies, in fact. Dropping the technical one is no good if a literary
one takes its place -- a story about the reed beds of Waverfen buries the
problem just as thoroughly as one about subarrays, and costs the mob the first
ten minutes of the session working out what a dyke is. Plain words throughout.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from .bench import MIN_GAP, MODELS, ORDER
from .errors import MobError

DIFFICULTIES = ("easy", "medium", "hard")
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
# The title line `render_main` writes, read back to find out what a repository
# has already produced.
TITLE_LINE = re.compile(r"^# (?P<title>.+?)  \((?:easy|medium|hard)\)$", re.MULTILINE)

# Settings, not problem types. The model is asked to take one, which pushes the
# *framing* apart without constraining the algorithm underneath -- a stateless
# call given the same brief twice will otherwise land on the same handful of
# canonical problems however high the sampling temperature is. The list is long
# and the suggestion is advisory, so exercises do not come out formulaic.
#
# Every one is somewhere an ordinary person has been. An earlier list ran to
# salt pans, peat bogs and letterpress printing, and the exercises followed it
# into the vocabulary those trades need -- firn, dyke, quire. A setting with no
# common words available forces uncommon ones, whatever the prompt asks for.
SETTINGS = (
    "a bike repair shop",
    "a school canteen",
    "parcel deliveries",
    "a swimming pool timetable",
    "a multi-storey car park",
    "supermarket checkouts",
    "a bus route",
    "a lending library",
    "a camping trip",
    "a football league",
    "a farmers' market",
    "a hospital waiting room",
    "moving house",
    "a village bakery",
    "ferry crossings",
    "a music festival",
    "a climbing wall",
    "a board game night",
    "a laundrette",
    "a taxi rank",
    "a fire station",
    "a vegetable garden",
    "an office printer",
    "a ski lift",
    "a vending machine",
    "railway timetables",
    "a charity shop",
    "a driving school",
    "a coffee shop",
    "a warehouse night shift",
    "a weather station",
    "a chess club",
    "a lost property office",
    "a marathon",
    "a fishing trip",
    "a hotel breakfast",
    "a scout camp",
    "recycling collections",
    "a cinema's screens",
    "a phone repair counter",
)

# Phrases that can only be there to name the technique. A statement containing
# one of these is thrown away. The signature is exempt -- it has to say
# `list[int]` sooner or later; the story never has to say "subarray".
TECHNIQUE_WORDS = (
    "subarray",
    "substring",
    "sliding window",
    "two pointer",
    "two-pointer",
    "prefix sum",
    "dynamic programming",
    "memoi",
    "backtrack",
    "binary search",
    "hash map",
    "hashmap",
    "hash table",
    "linked list",
    "binary tree",
    "priority queue",
    "depth-first",
    "breadth-first",
    "brute force",
    "algorithm",
    "data structure",
    "asymptotic",
    "complexity",
    "o(n",
    "time limit",
    "leetcode",
)

# Words with an innocent life outside computing: a queue of people, a stack of
# crates, a string of lights. These are only a smell, so they are reported and
# left to the mob to judge -- a false rejection costs a whole regeneration.
SOFT_WORDS = (
    "array",
    "index",
    "queue",
    "stack",
    "heap",
    "node",
    "vertex",
    "graph",
    "pointer",
    "greedy",
    "hash",
)

SYSTEM_PROMPT = """\
You design programming exercises for a mob-programming session. Each one is
scaffolded into a Python package, handed to a group of developers with the
solution stripped out, and solved test-first.

WHAT MAKES A GOOD EXERCISE HERE

Take the rigour of a competitive-programming problem: a difficulty tier, a
canonical algorithm or data structure underneath, exactly one correct answer for
any valid input, and a solution that is meaningfully cheaper than the obvious
one.

Take the framing of Advent of Code: the problem happens in a real or invented
world, to people or things, and it is comprehensible to someone who does not
program. A bus driver working out the busiest part of the route. A courier
picking which parcels fit in the van. A cafe deciding when to open a second
till.

The framing is not decoration, it is the exercise. "Given an integer array nums,
return the maximum sum of any contiguous block of length k" tells the solver
which technique to reach for before they have finished reading. "The cafe wants
to know its busiest four hours in a row" does not. The modelling is the part
worth practising.

RULES FOR THE LANGUAGE

The mob reads the statement out loud, together, and English is not everyone's
first language. Every minute spent decoding the prose is a minute not spent on
the problem, and a story nobody can picture hides the problem instead of posing
it. Plain beats vivid here, every time.

- Everyday words only. If a word would send a competent non-native speaker to a
  dictionary, it is the wrong word: "water level", not "tidal datum"; "shelf",
  not "gantry"; "left over", not "residual"; "grows", not "accrues".
- Short sentences, one idea each. If a sentence needs a comma to hold two halves
  together, it is usually two sentences.
- Ordinary and present-day: a bike shop, a bus route, a school canteen. No
  antique trades, no invented place names, no dialect, nothing that needs local
  knowledge to picture. A silly premise is welcome -- Advent of Code is full of
  them -- but the words in it still have to be words everyone knows.
- No ornament. Cut every adjective that does not change the answer. The story is
  there to be understood once, quickly, not admired.
- Title it after what is being worked out, in the same plain words: "The Busiest
  Four Hours", "Two Deliveries That Fit". Never "The Reed Beds of Waverfen".
- This applies to every word you write, the one-line reason on each example
  included.

RULES FOR THE STORY

- Never name a data structure, an algorithm, or a technique. Not in the story,
  not in the task sentence, not in the constraints, not in an example's comment.
  These are rejected outright and the exercise is thrown away: subarray,
  substring, sliding window, two pointers, prefix sum, dynamic programming,
  memoisation, backtracking, binary search, hash map, linked list, binary tree,
  priority queue, depth-first, breadth-first, brute force, algorithm, data
  structure, complexity, O(n), time limit.
- Avoid array, index, queue, stack, heap, node, graph, pointer and greedy too.
  A queue of people and a stack of crates are ordinary English, so these are not
  automatically fatal, but reach for the story's own word first.
- Never mention performance, time limits or efficiency. The scaling test says
  that, and it says it better.
- Name the parameters after what they are in the story -- `readings`, `parcels`,
  `patrol_days` -- never `nums`, `arr`, `s` or `k` alone.
- Be exact anyway. State precisely what to return, including what happens for
  the awkward inputs: empty, all-equal, ties, and the smallest legal size. A
  reader must never have to guess, and there must be exactly one right answer.
- Give the bounds in the story's own terms ("the shop serves at most a million
  customers a day, and each one takes between 1 and 600 seconds at the till").

RULES FOR THE SOLUTION

- One `class Solution` with exactly one public method, plus private helpers if
  you genuinely need them.
- Python 3.13, standard library only. Builtin generics: `list[int]`, not
  `List[int]` -- `typing.List` is deprecated and the repository's linter rejects
  it. Annotate every parameter and the return.
- It must be the good solution, not the obvious one.

RULES FOR THE EXAMPLES

Each example is the body of a test. Write real Python: call the method, assert
on what comes back. This is where you handle anything an equality check cannot
express -- work done in place, answers valid in any order, floating point. Use
`pytest.approx` for floats. At least three examples: the one from the story, an
edge case, and one that would catch a plausible off-by-one.

RULES FOR THE SCALING TEST

`generator` is the source of `def build(n, rng)`, returning the argument tuple
for the method. `n` must drive the dominant dimension, `rng` is a seeded
`random.Random`, and the instance it builds must be a hard one -- not sorted,
not all-equal, nothing that lets a poor solution finish early.

`sizes` is five strictly increasing values spanning at least 30x, chosen so the
good solution takes roughly a millisecond at the smallest and stays under a
second at the largest.

`intended_complexity` and `brute_force_complexity` come from the fixed list, and
must be at least two steps apart on it -- timing cannot separate O(n) from
O(n log n), so a problem whose obvious answer is only a log factor worse is not
usable here. Pick a problem with a real gap: linear against quadratic, or
linearithmic against quadratic.

Return the JSON object and nothing else.\
"""

COMPLEXITY_ENUM = list(MODELS)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "difficulty",
        "story",
        "task",
        "constraints",
        "entry_point",
        "solution",
        "examples",
        "generator",
        "sizes",
        "intended_complexity",
        "brute_force_complexity",
    ],
    "properties": {
        "title": {
            "type": "string",
            "description": (
                "What is being worked out, in everyday words, e.g. 'The Busiest "
                "Four Hours'. No jargon, no invented place names."
            ),
            "maxLength": 60,
        },
        "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
        "story": {
            "type": "string",
            "description": (
                "The situation, in one or two short paragraphs, 120 words at "
                "most. Everyday words and short sentences: someone who does not "
                "program must follow it on one reading, and a competent "
                "non-native English speaker must never need a dictionary."
            ),
        },
        "task": {
            "type": "string",
            "description": (
                "Exactly what the method must return, stated so precisely that "
                "no input has two defensible answers -- and in the same plain words."
            ),
        },
        "constraints": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Bounds and guarantees, phrased in the story's own plain terms.",
        },
        "entry_point": {
            "type": "string",
            "description": "The public method's name, snake_case, named for what it does.",
        },
        "solution": {
            "type": "string",
            "description": (
                "Source of the whole `class Solution`, the good solution, fully "
                "type-annotated. This is stripped to a skeleton before anyone sees it."
            ),
        },
        "examples": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "why", "code"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "snake_case, completing 'test_...'",
                    },
                    "why": {
                        "type": "string",
                        "description": (
                            "One plain line: what this example pins down. It becomes "
                            "the test's docstring, so the mob reads it too."
                        ),
                    },
                    "code": {
                        "type": "string",
                        "description": (
                            "The test body. Calls Solution().<entry_point>(...) and "
                            "asserts. `pytest` is imported for you."
                        ),
                    },
                },
            },
        },
        "generator": {
            "type": "string",
            "description": (
                "Source of `def build(n: int, rng: random.Random) -> tuple`, "
                "returning the argument tuple. Must build a hard instance."
            ),
        },
        "sizes": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 4,
            "maxItems": 6,
            "description": "Strictly increasing input sizes spanning at least 30x.",
        },
        "intended_complexity": {"type": "string", "enum": COMPLEXITY_ENUM},
        "brute_force_complexity": {"type": "string", "enum": COMPLEXITY_ENUM},
    },
}


@dataclass(frozen=True)
class Example:
    name: str
    why: str
    code: str


@dataclass(frozen=True)
class Kata:
    title: str
    difficulty: str
    story: str
    task: str
    constraints: list[str]
    entry_point: str
    solution: str
    examples: list[Example]
    generator: str
    sizes: list[int]
    intended_complexity: str
    brute_force_complexity: str

    @property
    def statement(self) -> str:
        """The story, the task and the constraints, as one block of prose."""
        parts = [self.title, "", self.story.strip(), "", self.task.strip(), "", "Constraints:"]
        parts += [f"  - {line}" for line in self.constraints]
        return "\n".join(parts)


class KataRejected(MobError):
    """The generated exercise broke a rule we cannot fix by editing it."""


def _reject(reason: str) -> NoReturn:
    raise KataRejected(
        f"the generated exercise was rejected: {reason}",
        hint="run `inv leetcode` again — generation is not deterministic",
    )


def _parses(source: str, what: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError as error:
        _reject(f"the {what} is not valid Python ({error.msg} on line {error.lineno})")


def parse(payload: dict[str, Any]) -> Kata:
    """Turn the model's JSON into a Kata, refusing anything unusable.

    The CLI has already validated the payload against SCHEMA, so the checks here
    are the ones a schema cannot express: that the Python parses, that the
    promised method exists, that the two complexities are far enough apart to be
    told apart by timing, and that the story kept its side of the bargain.
    """
    kata = Kata(
        title=payload["title"].strip(),
        difficulty=payload["difficulty"],
        story=payload["story"],
        task=payload["task"],
        constraints=list(payload["constraints"]),
        entry_point=payload["entry_point"].strip(),
        solution=payload["solution"],
        examples=[Example(**example) for example in payload["examples"]],
        generator=payload["generator"],
        sizes=list(payload["sizes"]),
        intended_complexity=payload["intended_complexity"],
        brute_force_complexity=payload["brute_force_complexity"],
    )
    validate(kata)
    return kata


def validate(kata: Kata) -> None:
    if not IDENTIFIER.match(kata.entry_point):
        _reject(f"{kata.entry_point!r} is not a usable method name")

    tree = _parses(kata.solution, "solution")
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1 or classes[0].name != "Solution":
        _reject("the solution must be exactly one `class Solution`")
    methods = [node for node in classes[0].body if isinstance(node, ast.FunctionDef)]
    public = [node for node in methods if not node.name.startswith("_")]
    if [node.name for node in public] != [kata.entry_point]:
        found = ", ".join(node.name for node in public) or "none"
        _reject(f"expected one public method {kata.entry_point!r}, found: {found}")

    generator = _parses(kata.generator, "generator")
    builders = [
        node
        for node in generator.body
        if isinstance(node, ast.FunctionDef) and node.name == "build"
    ]
    if not builders:
        _reject("the generator must define `build(n, rng)`")
    if [argument.arg for argument in builders[0].args.args] != ["n", "rng"]:
        _reject("`build` must take exactly (n, rng)")

    for example in kata.examples:
        if not IDENTIFIER.match(example.name):
            _reject(f"{example.name!r} is not a usable test name")
        _parses(example.code, f"example {example.name!r}")
        if kata.entry_point not in example.code:
            _reject(f"example {example.name!r} never calls {kata.entry_point}()")

    if kata.sizes != sorted(set(kata.sizes)):
        _reject("the sizes must be strictly increasing")
    if kata.sizes[-1] / kata.sizes[0] < 30:
        _reject(f"the sizes span only {kata.sizes[-1] / kata.sizes[0]:.0f}x, which is too narrow")

    gap = ORDER[kata.brute_force_complexity] - ORDER[kata.intended_complexity]
    if gap < MIN_GAP:
        _reject(
            f"O({kata.intended_complexity}) and O({kata.brute_force_complexity}) are "
            "too close to tell apart by timing"
        )

    if found := words_in(kata, TECHNIQUE_WORDS):
        _reject(f"the statement gives the technique away: {', '.join(sorted(found))}")


def build_prompt(
    brief: str,
    *,
    already_done: Sequence[str] = (),
    settings: Sequence[str] = (),
    nonce: int = 0,
    complaint: str | None = None,
) -> str:
    """The user turn.

    The nonce and the settings are the whole answer to "it is stateless, so how
    does it not repeat itself". The CLI exposes no temperature or seed, and
    sampling alone does not help much anyway: asked twice for a sliding-window
    problem a model lands on the same canonical one, because that is where the
    probability mass is. Moving the *prompt* is what moves the answer.
    """
    parts = [f"Design one exercise. The mob asked for: {brief}"]
    if settings:
        listed = "; ".join(settings)
        parts.append(
            f"For the setting, take one of these and run with it: {listed}. "
            "Or invent something else entirely, as long as it is nothing like "
            "the ones already produced below."
        )
    if already_done:
        listed = "\n".join(f"  - {title}" for title in already_done)
        parts.append(
            "This mob has already worked through the following. Do not repeat "
            f"any of them, in substance or in setting:\n{listed}"
        )
    if complaint:
        parts.append(f"A previous attempt was thrown away because {complaint}. Avoid that.")
    # Last, so it is the freshest thing in context. "Make this one distinct" on
    # its own was read as licence to be exotic, and the cheapest axis of exotic
    # is vocabulary -- so it says which axis to be distinct on.
    parts.append(
        f"Variation {nonce}. Make this one distinct in situation and in what has "
        "to be worked out. Not in vocabulary: keep the words plain."
    )
    return "\n\n".join(parts)


def summarise(source: str, limit: int = 240) -> str | None:
    """One line describing an exercise, read back out of its `main.py`.

    Nothing is stored to make this work: the scaffolded package *is* the record,
    and every past exercise is already sitting in git. Titles alone are not
    enough to prevent a repeat -- "The Kiln's Steady Soak" says nothing about
    what had to be computed -- so this carries the method name and the task
    sentence as well, which is what the next exercise has to differ from.
    """
    found = TITLE_LINE.search(source)
    if not found:
        return None

    comments: list[str] = []
    for line in source.splitlines():
        if line.startswith("#"):
            comments.append(line[1:].strip())
        elif comments and not line.strip():
            continue
        elif comments:
            break

    paragraphs: list[str] = []
    current: list[str] = []
    for line in comments:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))

    # The task is the last paragraph before the constraints, which is where
    # `render_main` puts it.
    body = [p for p in paragraphs[1:] if not p.startswith("Constraints:")]
    task = body[-1] if body else ""

    entry = re.search(r"def (\w+)\(self", source)
    method = f" [{entry.group(1)}]" if entry else ""
    return f"{found.group('title')}{method}: {task[:limit]}"


def prose_of(kata: Kata) -> str:
    """Everything the solver reads before writing any code."""
    return " ".join(
        [kata.title, kata.story, kata.task, *kata.constraints, *(e.why for e in kata.examples)]
    ).lower()


def words_in(kata: Kata, vocabulary: tuple[str, ...]) -> set[str]:
    prose = prose_of(kata)
    return {word for word in vocabulary if word in prose}


def to_json(kata: Kata) -> str:
    """Round-trippable, for the fixtures the tests are built from."""
    return json.dumps(
        {
            **{
                field: getattr(kata, field)
                for field in (
                    "title",
                    "difficulty",
                    "story",
                    "task",
                    "constraints",
                    "entry_point",
                    "solution",
                    "generator",
                    "sizes",
                    "intended_complexity",
                    "brute_force_complexity",
                )
            },
            "examples": [vars(example) for example in kata.examples],
        },
        indent=2,
    )
