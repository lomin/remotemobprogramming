# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""The command line surface.

Argument wiring is easy to break without any test noticing, because the tasks
themselves are thin and the parsing happens inside Invoke.
"""

from __future__ import annotations

import pytest
from invoke.parser import Parser, ParserContext

import tasks

MOB_TASKS = ["mob.start", "mob.branch", "mob.list", "mob.next", "mob.drive", "mob.name"]
TEST_TASKS = ["test.self", "test.run", "test.submit"]


def parse(argv: list[str]) -> dict:
    task = tasks.namespace.task_with_config(argv[0])[0]
    context = ParserContext(name=argv[0], args=task.get_arguments())
    result = Parser(contexts=[context]).parse_argv(argv)
    return {name: arg.value for name, arg in result[0].args.items()}


def test_the_original_tasks_survive_the_explicit_namespace():
    # Invoke stops auto-collecting once a root namespace exists, so these have
    # to be registered by hand -- and would silently vanish if they were not.
    assert set(tasks.namespace.tasks) >= {"watch", "lint", "fmt", "install"}


@pytest.mark.parametrize("name", MOB_TASKS + TEST_TASKS)
def test_every_task_in_a_namespace_is_reachable(name):
    assert tasks.namespace.task_with_config(name)[0] is not None


def test_bare_inv_test_runs_the_session_exercise():
    # The common case during a session, so it gets the short spelling.
    assert tasks.namespace.task_with_config("test")[0] is tasks.test_run


def test_drive_defaults_to_the_latest_session():
    assert parse(["mob.drive"])["session"] is None


@pytest.mark.parametrize("flag", ["-s", "--session"])
def test_drive_takes_a_session_by_flag(flag):
    assert parse(["mob.drive", flag, "payments_spike"])["session"] == "payments_spike"


def test_name_takes_the_new_name_positionally():
    assert parse(["mob.name", "payments_spike"])["new-name"] == "payments_spike"


def test_name_can_target_another_session():
    parsed = parse(["mob.name", "spike", "--session", "mob/20260812T143005Z"])

    assert parsed["new-name"] == "spike"
    assert parsed["session"] == "mob/20260812T143005Z"


def test_start_takes_a_name_and_a_base():
    parsed = parse(["mob.start", "-n", "groundwork", "-b", "develop"])

    assert (parsed["name"], parsed["base"]) == ("groundwork", "develop")


def test_list_takes_its_two_switches():
    parsed = parse(["mob.list", "--all", "--no-fetch"])

    assert parsed["all"] is True
    assert parsed["no-fetch"] is True


def test_next_takes_a_message():
    assert parse(["mob.next", "-m", "add the thing"])["message"] == "add the thing"
