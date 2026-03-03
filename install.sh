#!/usr/bin/env bash
# big-brain installer
# Run from the repo root: bash install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/bigbrain"
CONFIG_FILE="$CONFIG_DIR/config.toml"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}▸${NC} $*"; }
warn()    { echo -e "${YELLOW}▸${NC} $*"; }
err()     { echo -e "${RED}✗${NC} $*" >&2; }
heading() { echo -e "\n${BOLD}$*${NC}"; }

# ── Prerequisites ─────────────────────────────────────────────────────────────

heading "Checking prerequisites"

# Python 3.11+
if ! command -v python3 &>/dev/null; then
    err "python3 not found. Install Python 3.11+ and try again."
    exit 1
fi

PYTHON_OK=$(python3 -c 'import sys; print("ok" if sys.version_info >= (3, 11) else "old")')
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$PYTHON_OK" != "ok" ]]; then
    err "Python 3.11+ required (found $PY_VER)"
    exit 1
fi
info "Python $PY_VER ✓"

# pip
if ! python3 -m pip --version &>/dev/null; then
    err "pip not found. Install pip and try again."
    exit 1
fi

# ── Install package ───────────────────────────────────────────────────────────

heading "Installing big-brain"
python3 -m pip install --user -e "$REPO_DIR" --quiet
info "Package installed (editable/dev mode)"

# Ensure ~/.local/bin is in PATH
LOCAL_BIN="$HOME/.local/bin"
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    warn "~/.local/bin is not in your PATH."
    warn "Add this to your shell rc file and restart your shell:"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# Verify bb is reachable
if ! command -v bb &>/dev/null; then
    # Try running via python -m as fallback
    BB_CMD="python3 -m bb.cli.main"
    warn "'bb' not in PATH yet — you may need to restart your shell."
else
    BB_CMD="bb"
    info "bb command found: $(command -v bb)"
fi

# ── Config ────────────────────────────────────────────────────────────────────

heading "Setting up config"

mkdir -p "$CONFIG_DIR"

if [[ -f "$CONFIG_FILE" ]]; then
    info "Config already exists: $CONFIG_FILE"
else
    cp "$REPO_DIR/config.example.toml" "$CONFIG_FILE"
    info "Created config: $CONFIG_FILE"
fi

# If Ollama is running and config still says "noop", switch it to "ollama"
if curl -sf --max-time 2 http://localhost:11434/api/tags &>/dev/null; then
    info "Ollama detected ✓"
    if grep -q 'provider = "noop"' "$CONFIG_FILE"; then
        sed -i 's/^provider = "noop"/provider = "ollama"/' "$CONFIG_FILE"
        info "Switched LLM provider to 'ollama' in config"
    fi

    # Check if recommended model is pulled
    MODEL="alibayram/Qwen3-30B-A3B-Instruct-2507:latest"
    if curl -sf http://localhost:11434/api/tags | python3 -c "
import json, sys
models = [m['name'] for m in json.load(sys.stdin).get('models', [])]
exit(0 if any('Qwen3-30B' in m or 'Qwen3-30B-A3B' in m for m in models) else 1)
" 2>/dev/null; then
        info "Qwen3-30B-A3B model found ✓"
    else
        warn "Recommended model not pulled yet. For best context estimation:"
        warn "  ollama pull $MODEL"
    fi
else
    warn "Ollama not detected — context estimation will be disabled (provider = noop)"
    warn "Start Ollama or set provider = 'anthropic' in $CONFIG_FILE"
fi

# ── Shell hook ────────────────────────────────────────────────────────────────

heading "Setting up shell hook (terminal history capture)"

SHELL_NAME="$(basename "${SHELL:-bash}")"

case "$SHELL_NAME" in
    bash)
        RC_FILE="$HOME/.bashrc"
        HOOK_LINE='source "$(bb shell-hook-path bash)"'
        ;;
    zsh)
        RC_FILE="$HOME/.zshrc"
        HOOK_LINE='source "$(bb shell-hook-path zsh)"'
        ;;
    *)
        RC_FILE=""
        warn "Unknown shell '$SHELL_NAME' — skipping automatic hook setup"
        warn "Manually add to your shell rc: source \"\$(bb shell-hook-path bash)\""
        ;;
esac

if [[ -n "${RC_FILE:-}" ]]; then
    if grep -q "bb shell-hook-path" "$RC_FILE" 2>/dev/null; then
        info "Shell hook already in $RC_FILE"
    else
        {
            echo ""
            echo "# big-brain: capture terminal history"
            echo "$HOOK_LINE"
        } >> "$RC_FILE"
        info "Added shell hook to $RC_FILE"
    fi
fi

# ── Daemon ────────────────────────────────────────────────────────────────────

heading "Starting daemon"

DATA_DIR="$HOME/.local/share/bigbrain"
PID_FILE="$DATA_DIR/daemon.pid"

_daemon_running() {
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null) || return 1
    kill -0 "$pid" 2>/dev/null
}

if _daemon_running; then
    info "Daemon already running (PID $(cat "$PID_FILE"))"
else
    $BB_CMD daemon start 2>/dev/null && info "Daemon started" || warn "Could not start daemon — run 'bb daemon start' manually after reloading your shell"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Installation complete!${NC}"
echo ""
echo "  Reload your shell to activate terminal history capture:"
echo "    source $RC_FILE"
echo ""
echo "  Quick start:"
echo "    bb add 'first thought'"
echo "    bb search 'thought'"
echo "    bb digest"
echo "    bb llm test"
echo ""
echo "  Config: $CONFIG_FILE"
echo "  Data:   $DATA_DIR"
echo "  Logs:   $DATA_DIR/daemon.log"
echo ""
