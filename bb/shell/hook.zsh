# big-brain shell hook for zsh
# Add to your ~/.zshrc:
#   source "$(bb shell-hook-path zsh)"

_BB_CAPTURE_SCRIPT="$(python3 -c 'import importlib.resources; print(importlib.resources.files("bb.shell") / "capture.py")' 2>/dev/null)"
_BB_LAST_CMD=""

# preexec runs before each command — captures what's about to run
_bb_preexec() {
    _BB_LAST_CMD="$1"
}

# precmd runs after each command — sends it to the daemon
_bb_precmd() {
    local exit_code=$?
    local cmd="$_BB_LAST_CMD"

    [ -z "$_BB_CAPTURE_SCRIPT" ] && return
    [ -z "$cmd" ] && return

    python3 "$_BB_CAPTURE_SCRIPT" "$cmd" "$PWD" "$exit_code" &>/dev/null &
    disown 2>/dev/null
}

autoload -Uz add-zsh-hook
add-zsh-hook preexec _bb_preexec
add-zsh-hook precmd _bb_precmd
