# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
"""The one exception type the tasks turn into readable terminal output."""

from __future__ import annotations


class MobError(Exception):
    """Something the user can act on. Carries an optional hint line."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)
