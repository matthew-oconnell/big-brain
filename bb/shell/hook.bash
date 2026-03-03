# big-brain shell hook for bash
# Add to your ~/.bashrc:
#   source "$(bb shell-hook-path bash)"

_BB_CAPTURE_SCRIPT="$(python3 -c 'import importlib.resources; print(importlib.resources.files("bb.shell") / "capture.py")' 2>/dev/null)"
_BB_LAST_CAPTURED=""

_bb_capture() {
    local exit_code=$?

    # Skip if capture script not found (package not installed)
    [ -z "$_BB_CAPTURE_SCRIPT" ] && return 0

    # Get the last command from history
    local cmd
    cmd=$(HISTTIMEFORMAT= history 1 | sed 's/^[ ]*[0-9]*[ ]*//')

    # Skip empty or duplicate of last captured
    [ -z "$cmd" ] && return 0
    [ "$cmd" = "$_BB_LAST_CAPTURED" ] && return 0
    _BB_LAST_CAPTURED="$cmd"

    # Fire and forget — don't block the prompt
    python3 "$_BB_CAPTURE_SCRIPT" "$cmd" "$PWD" "$exit_code" &>/dev/null &
    disown 2>/dev/null

    return 0
}

# Prepend to PROMPT_COMMAND (safe to source multiple times)
if [[ ! "${PROMPT_COMMAND:-}" =~ _bb_capture ]]; then
    PROMPT_COMMAND="_bb_capture${PROMPT_COMMAND:+;${PROMPT_COMMAND}}"
fi
