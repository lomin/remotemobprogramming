#!/bin/sh
# Activate the project virtualenv.
#
#     source ./active.sh
#
# This MUST be sourced, not executed. Running it as ./active.sh activates the
# venv inside a subprocess that then exits, leaving your shell untouched.
#
# Creates the venv first if it is missing, so this works on a fresh clone.
#
# Note: an activated shell does not re-sync. If someone runs `uv add`, run
# `uv sync` to catch up — or just use `uv run inv <task>`, which always syncs.

# --- refuse to run as a subprocess -------------------------------------------
__sourced=0
if [ -n "$ZSH_VERSION" ]; then
    case $ZSH_EVAL_CONTEXT in *:file) __sourced=1 ;; esac
elif [ -n "$BASH_VERSION" ]; then
    [ "${BASH_SOURCE[0]}" != "$0" ] && __sourced=1
else
    case $0 in *active.sh) __sourced=0 ;; *) __sourced=1 ;; esac
fi

if [ "$__sourced" -eq 0 ]; then
    echo "active.sh must be sourced, not executed." >&2
    echo "" >&2
    echo "    source ./active.sh" >&2
    echo "" >&2
    echo "Or skip activation entirely: uv run inv <task>" >&2
    unset __sourced
    exit 1
fi
unset __sourced

# --- locate this script (differs per shell when sourced) ---------------------
if [ -n "$ZSH_VERSION" ]; then
    __src=$0
elif [ -n "$BASH_VERSION" ]; then
    __src=${BASH_SOURCE[0]}
else
    __src=./active.sh
fi
__root=$(cd "$(dirname "$__src")" >/dev/null 2>&1 && pwd) || __root=$PWD

# --- activate ----------------------------------------------------------------

if [ ! -d "$__root/.venv" ]; then
    echo "No .venv found — creating it with uv sync..."
    uv sync --project "$__root" || return 1
fi

. "$__root/.venv/bin/activate"
echo "venv active: $VIRTUAL_ENV"
echo "run 'deactivate' to exit"
