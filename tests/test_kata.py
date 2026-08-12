# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""What we insist on before an exercise is allowed near the repository.

The CLI validates the payload against the schema, so nothing here re-checks
types or required keys. These are the rules a JSON schema cannot state.
"""

from __future__ import annotations

import copy

import pytest

from remotemobprogramming.kata import (
    SCHEMA,
    SOFT_WORDS,
    KataRejected,
    build_prompt,
    parse,
    summarise,
    words_in,
)

PAYLOAD = {
    "title": "The Tidal Ledger",
    "difficulty": "medium",
    "story": (
        "The harbour master keeps a ledger of water levels, one reading every "
        "quarter hour, going back years. The mooring fees depend on the calmest "
        "stretch of any given length: the fewer millimetres the water moved, the "
        "cheaper the berth."
    ),
    "task": (
        "Return the smallest difference between the highest and lowest reading "
        "across any run of exactly `span` consecutive readings. If several runs "
        "tie, return that shared difference."
    ),
    "constraints": [
        "there is at least one reading and at most a million",
        "`span` is between 1 and the number of readings",
        "every reading is a whole number of millimetres between -10000 and 10000",
    ],
    "entry_point": "calmest_stretch",
    "solution": (
        "class Solution:\n"
        "    def calmest_stretch(self, readings: list[int], span: int) -> int:\n"
        "        return max(readings[:span]) - min(readings[:span])\n"
    ),
    "examples": [
        {
            "name": "the_harbour_masters_own_worked_case",
            "why": "the one spelled out in the ledger",
            "code": "assert Solution().calmest_stretch([4, 9, 1, 2], 2) == 1",
        },
        {
            "name": "a_single_reading_never_moves",
            "why": "the smallest legal run",
            "code": "assert Solution().calmest_stretch([7], 1) == 0",
        },
        {
            "name": "a_run_covering_every_reading",
            "why": "catches an off-by-one at the far end",
            "code": "assert Solution().calmest_stretch([4, 9, 1, 2], 4) == 8",
        },
    ],
    "generator": (
        "def build(n, rng):\n"
        "    return ([rng.randrange(-10000, 10000) for _ in range(n)], max(2, n // 8))\n"
    ),
    "sizes": [2000, 8000, 32000, 128000, 512000],
    "intended_complexity": "n",
    "brute_force_complexity": "n^2",
}


def payload(**overrides) -> dict:
    merged = copy.deepcopy(PAYLOAD)
    merged.update(overrides)
    return merged


def test_a_well_formed_exercise_is_accepted():
    kata = parse(payload())

    assert kata.title == "The Tidal Ledger"
    assert kata.entry_point == "calmest_stretch"
    assert len(kata.examples) == 3


def test_the_statement_reads_as_one_block():
    statement = parse(payload()).statement

    assert statement.startswith("The Tidal Ledger")
    assert "Constraints:" in statement
    assert "  - there is at least one reading" in statement


# -- the solution -----------------------------------------------------------


def test_a_solution_that_does_not_parse_is_refused():
    with pytest.raises(KataRejected, match="not valid Python"):
        parse(payload(solution="class Solution:\n    def f(self) ->\n"))


def test_the_solution_has_to_be_a_single_Solution_class():
    with pytest.raises(KataRejected, match="one `class Solution`"):
        parse(payload(solution="def calmest_stretch(readings, span):\n    return 0\n"))


def test_the_promised_method_has_to_exist():
    with pytest.raises(KataRejected, match="found: something_else"):
        parse(
            payload(
                solution=(
                    "class Solution:\n"
                    "    def something_else(self, readings: list[int]) -> int:\n"
                    "        return 0\n"
                )
            )
        )


def test_private_helpers_are_allowed():
    kata = parse(
        payload(
            solution=(
                "class Solution:\n"
                "    def calmest_stretch(self, readings: list[int], span: int) -> int:\n"
                "        return self._sweep(readings, span)\n"
                "\n"
                "    def _sweep(self, readings: list[int], span: int) -> int:\n"
                "        return 0\n"
            )
        )
    )

    assert kata.entry_point == "calmest_stretch"


def test_a_second_public_method_is_refused():
    # Two entry points means the test file and the skeleton disagree about what
    # is being solved.
    with pytest.raises(KataRejected, match="expected one public method"):
        parse(
            payload(
                solution=(
                    "class Solution:\n"
                    "    def calmest_stretch(self, readings: list[int], span: int) -> int:\n"
                    "        return 0\n"
                    "\n"
                    "    def also_this(self) -> int:\n"
                    "        return 0\n"
                )
            )
        )


# -- the examples -----------------------------------------------------------


def test_an_example_that_never_calls_the_method_is_refused():
    with pytest.raises(KataRejected, match="never calls"):
        parse(
            payload(
                examples=[
                    {**PAYLOAD["examples"][0], "code": "assert 1 + 1 == 2"},
                    *PAYLOAD["examples"][1:],
                ]
            )
        )


def test_an_example_that_does_not_parse_is_refused():
    with pytest.raises(KataRejected, match="not valid Python"):
        parse(
            payload(
                examples=[
                    {**PAYLOAD["examples"][0], "code": "assert Solution().calmest_stretch(("},
                    *PAYLOAD["examples"][1:],
                ]
            )
        )


def test_a_test_name_that_is_not_an_identifier_is_refused():
    with pytest.raises(KataRejected, match="not a usable test name"):
        parse(
            payload(
                examples=[
                    {**PAYLOAD["examples"][0], "name": "the harbour master's case"},
                    *PAYLOAD["examples"][1:],
                ]
            )
        )


# -- the scaling test -------------------------------------------------------


def test_the_generator_has_to_define_build():
    with pytest.raises(KataRejected, match="must define `build"):
        parse(payload(generator="def make_input(n, rng):\n    return ([], 1)\n"))


def test_the_generator_has_to_take_n_and_rng():
    with pytest.raises(KataRejected, match=r"exactly \(n, rng\)"):
        parse(payload(generator="def build(size, seed, extra):\n    return ([], 1)\n"))


def test_sizes_that_do_not_climb_are_refused():
    with pytest.raises(KataRejected, match="strictly increasing"):
        parse(payload(sizes=[2000, 8000, 4000, 128000, 512000]))


def test_sizes_too_close_together_are_refused():
    with pytest.raises(KataRejected, match="too narrow"):
        parse(payload(sizes=[2000, 4000, 8000, 16000, 20000]))


def test_two_complexities_a_log_factor_apart_are_refused():
    # This is the one thing timing genuinely cannot settle, so the problem is
    # thrown away rather than tested unreliably.
    with pytest.raises(KataRejected, match="too close to tell apart"):
        parse(payload(intended_complexity="n", brute_force_complexity="n log n"))


def test_a_full_degree_apart_is_enough():
    assert parse(payload(intended_complexity="n log n", brute_force_complexity="n^2"))


# -- the framing ------------------------------------------------------------


@pytest.mark.parametrize(
    "giveaway",
    [
        "Return the maximum sum of any subarray of that length.",
        "Use a sliding window over the readings.",
        "This must run in O(n log n) time.",
        "The obvious dynamic programming answer is too slow.",
    ],
)
def test_a_statement_that_names_the_technique_is_thrown_away(giveaway):
    with pytest.raises(KataRejected, match="gives the technique away"):
        parse(payload(task=giveaway))


def test_the_giveaway_is_named_so_the_next_attempt_can_avoid_it():
    with pytest.raises(KataRejected, match="sliding window"):
        parse(payload(story="Slide a sliding window along the ledger."))


def test_ordinary_english_survives_the_jargon_filter():
    # A queue of people and a stack of crates are what the story is *about*.
    kata = parse(
        payload(
            story=(
                "A queue forms at the harbour office each morning, and a stack of "
                "ledgers waits on the desk."
            )
        )
    )

    assert words_in(kata, SOFT_WORDS) == {"queue", "stack"}


def test_the_signature_may_say_what_the_story_may_not():
    # `list[int]` is unavoidable in Python; the point is that the prose never
    # had to say it.
    kata = parse(payload())

    assert "list[int]" in kata.solution
    assert "list" not in kata.story


# -- the prompt -------------------------------------------------------------


def test_the_brief_is_passed_through_verbatim():
    assert "prefix sums, on the hard side" in build_prompt("prefix sums, on the hard side")


def test_the_nonce_is_last_so_it_is_freshest_in_context():
    prompt = build_prompt("anything", nonce=4712)

    assert "Variation 4712." in prompt.rstrip().rsplit("\n\n", 1)[-1]


def test_being_distinct_is_asked_for_in_the_situation_and_not_in_the_words():
    # "Make this one distinct" alone came back as unusual vocabulary, which is
    # the cheapest way to be unusual and the least useful.
    prompt = build_prompt("anything", nonce=4712)

    assert "keep the words plain" in prompt


def test_two_prompts_for_the_same_brief_differ():
    assert build_prompt("anything", nonce=1) != build_prompt("anything", nonce=2)


def test_the_settings_are_offered_rather_than_imposed():
    # A mandatory setting list would make every exercise feel stamped out.
    prompt = build_prompt("anything", settings=["beekeeping", "canal locks"])

    assert "beekeeping" in prompt
    assert "invent something else entirely" in prompt


def test_what_has_been_done_before_is_listed_out():
    prompt = build_prompt("anything", already_done=["The Tidal Ledger", "The Beekeeper's Round"])

    assert "  - The Tidal Ledger" in prompt
    assert "Do not repeat" in prompt


def test_a_rejection_reason_is_fed_back():
    prompt = build_prompt("anything", complaint="it named the technique")

    assert "it named the technique" in prompt


def test_a_past_exercise_is_read_back_out_of_its_own_package():
    # Nothing is stored to make this work. The scaffolded package is the record,
    # so a later session learns what an earlier one produced by reading it.
    from remotemobprogramming.scaffold import render_main

    summary = summarise(render_main(parse(payload())))

    assert summary.startswith("The Tidal Ledger [calmest_stretch]:")
    assert "smallest difference between the highest and lowest reading" in summary


def test_the_summary_carries_the_task_and_not_just_the_name():
    # A title alone cannot prevent a repeat: "The Kiln's Steady Soak" says
    # nothing about what had to be computed.
    summary = summarise(
        "# The Kiln's Steady Soak  (medium)\n"
        "#\n"
        "# Once upon a time in a pottery.\n"
        "#\n"
        "# Return the longest stretch held within two degrees.\n"
        "#\n"
        "# Constraints:\n"
        "#   - at most a million readings\n"
        "\n\nclass Solution:\n    def steady_soak(self, temperatures: list[int]) -> int:\n"
    )

    assert summary == (
        "The Kiln's Steady Soak [steady_soak]: Return the longest stretch held within two degrees."
    )


def test_something_that_is_not_an_exercise_summarises_to_nothing():
    assert summarise("# some ordinary comment\n# another (medium) aside") is None


# -- the schema itself ------------------------------------------------------


def test_the_schema_forbids_fields_we_did_not_ask_for():
    # Structured output is only a contract if the shape is closed.
    assert SCHEMA["additionalProperties"] is False
    assert all(
        definition.get("additionalProperties") is False
        for definition in [SCHEMA["properties"]["examples"]["items"]]
    )


def test_every_field_the_scaffolder_reads_is_required():
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])
