# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""The CLI client.

Nothing here spends a token. What is worth pinning down is the argument list --
`--tools ""` and a replacing `--system-prompt` are the difference between a
cheap one-shot call and an agent with file access -- and the handling of every
way the CLI can answer badly.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from remotemobprogramming.claude import Claude, ClaudeError, _structured

SCHEMA = {"type": "object", "properties": {"fruit": {"type": "string"}}}


def envelope(**fields) -> str:
    return json.dumps({"is_error": False, "type": "result", **fields})


class FakeRun:
    """Stands in for subprocess.run, remembering what it was called with."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.argv: list[str] = []

    def __call__(self, argv, **kwargs):
        self.argv = argv
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


@pytest.fixture
def fake(monkeypatch):
    def install(runner):
        monkeypatch.setattr(subprocess, "run", runner)
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        return runner

    return install


# -- the call ---------------------------------------------------------------


def test_the_structured_object_comes_back_parsed(fake):
    fake(FakeRun(envelope(structured_output={"fruit": "banana"})))

    assert Claude().ask("go", "be brief", SCHEMA) == {"fruit": "banana"}


def test_the_call_carries_the_schema_and_the_prompt(fake):
    runner = fake(FakeRun(envelope(structured_output={"fruit": "fig"})))

    Claude(model="sonnet").ask("pick a fruit", "you pick fruit", SCHEMA)

    assert runner.argv[-1] == "pick a fruit"
    assert "--print" in runner.argv
    assert runner.argv[runner.argv.index("--model") + 1] == "sonnet"
    assert json.loads(runner.argv[runner.argv.index("--json-schema") + 1]) == SCHEMA
    assert runner.argv[runner.argv.index("--output-format") + 1] == "json"


def test_the_call_has_no_tools(fake):
    # An agent that can read and write files is not what this is for, and it is
    # the difference between a cheap call and an expensive one.
    runner = fake(FakeRun(envelope(structured_output={"fruit": "fig"})))

    Claude().ask("go", "system", SCHEMA)

    assert runner.argv[runner.argv.index("--tools") + 1] == ""


def test_the_system_prompt_replaces_rather_than_appends(fake):
    # Appending would keep tens of thousands of tokens of instructions about
    # editing files, paid for on every generation.
    runner = fake(FakeRun(envelope(structured_output={"fruit": "fig"})))

    Claude().ask("go", "you design exercises", SCHEMA)

    assert "--append-system-prompt" not in runner.argv
    assert runner.argv[runner.argv.index("--system-prompt") + 1] == "you design exercises"


def test_a_missing_cli_says_where_to_get_it(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ClaudeError, match="not on your PATH") as caught:
        Claude().ask("go", "system", SCHEMA)

    assert "claude-code" in caught.value.hint


def test_a_timeout_is_reported_as_one(fake):
    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 300)

    fake(slow)

    with pytest.raises(ClaudeError, match="did not answer within"):
        Claude().ask("go", "system", SCHEMA)


def test_a_non_zero_exit_carries_the_last_line_of_the_complaint(fake):
    fake(FakeRun("", returncode=1, stderr="Credit balance is too low\n"))

    with pytest.raises(ClaudeError, match="exited with 1") as caught:
        Claude().ask("go", "system", SCHEMA)

    assert caught.value.hint == "Credit balance is too low"


# -- reading the envelope ---------------------------------------------------


def test_output_that_is_not_json_is_reported_with_what_was_printed():
    with pytest.raises(ClaudeError, match="not JSON") as caught:
        _structured("Usage: claude [options]")

    assert "Usage" in caught.value.hint


def test_an_empty_answer_says_so():
    with pytest.raises(ClaudeError, match="not JSON") as caught:
        _structured("")

    assert "nothing at all" in caught.value.hint


def test_an_error_envelope_is_not_mistaken_for_an_answer():
    payload = json.dumps({"is_error": True, "result": "rate limited"})

    with pytest.raises(ClaudeError, match="reported an error") as caught:
        _structured(payload)

    assert "rate limited" in caught.value.hint


def test_the_result_text_is_used_when_structured_output_is_missing():
    # Belt and braces: with a schema in force the result text *is* the object,
    # so a CLI that stops sending the parsed field is still usable.
    assert _structured(envelope(result='{"fruit": "quince"}')) == {"fruit": "quince"}


def test_prose_where_the_object_should_be_is_refused():
    with pytest.raises(ClaudeError, match="no structured output"):
        _structured(envelope(result="Sure! Here is a fruit: banana"))
