# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""Asking the `claude` CLI for a structured answer.

`--json-schema` makes the CLI validate the reply for us and hand it back already
parsed under `structured_output`, so there is no fenced markdown to strip and no
brace-hunting to do. If the model cannot satisfy the schema the CLI says so; we
never see a half-formed object.

The system prompt *replaces* rather than appends. Claude Code's own prompt is
tens of thousands of tokens of instructions about editing files and running
tools, none of which applies to writing one JSON object, and all of which is
paid for on every call.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from .errors import MobError

DEFAULT_TIMEOUT = 300.0


class ClaudeError(MobError):
    pass


@dataclass
class Claude:
    """A one-shot call to the CLI. No tools, no session, no conversation."""

    model: str = "sonnet"
    timeout: float = DEFAULT_TIMEOUT
    executable: str = "claude"
    extra: list[str] = field(default_factory=list)

    def ask(self, prompt: str, system: str, schema: dict[str, Any]) -> dict[str, Any]:
        if shutil.which(self.executable) is None:
            raise ClaudeError(
                f"{self.executable!r} is not on your PATH",
                hint="install the Claude Code CLI: https://claude.com/claude-code",
            )

        argv = [
            self.executable,
            "--print",
            "--model",
            self.model,
            # Nothing to read and nothing to write: the exercise comes back as
            # data and this process is what puts it on disk.
            "--tools",
            "",
            "--system-prompt",
            system,
            "--json-schema",
            json.dumps(schema),
            "--output-format",
            "json",
            *self.extra,
            prompt,
        ]

        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except subprocess.TimeoutExpired:
            raise ClaudeError(
                f"claude did not answer within {self.timeout:.0f}s",
                hint="try again, or raise timeout under [tool.mob] in pyproject.toml",
            ) from None

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            raise ClaudeError(
                f"claude exited with {result.returncode}",
                hint=detail[-1] if detail else None,
            )

        return _structured(result.stdout)


def _structured(stdout: str) -> dict[str, Any]:
    """Pull the validated object out of the CLI's result envelope."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        raise ClaudeError(
            "claude's output was not JSON",
            hint=stdout.strip()[:200] or "it printed nothing at all",
        ) from None

    if envelope.get("is_error"):
        raise ClaudeError("claude reported an error", hint=str(envelope.get("result"))[:200])

    payload = envelope.get("structured_output")
    if isinstance(payload, dict):
        return payload

    # Older CLIs, and any future one that drops the field, still put the model's
    # text in `result` -- and with a schema in force that text is the object.
    raw = envelope.get("result")
    if isinstance(raw, str):
        try:
            recovered = json.loads(raw)
        except json.JSONDecodeError:
            recovered = None
        if isinstance(recovered, dict):
            return recovered

    raise ClaudeError(
        "claude returned no structured output",
        hint="the CLI answered, but not against the schema it was given",
    )
