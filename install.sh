#!/usr/bin/env bash
# big-brain installer
# Run from the repo root: bash install.sh
#
# Uses a dedicated venv — avoids pip-not-found and Fedora's
# "externally-managed-environment" errors entirely.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$HOME/.local/share/bigbrain"
VENV_DIR="$DATA_DIR/venv"
BIN_DIR="$HOME/.local/bin"
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

if ! command -v python3 &>/dev/null; then
    err "python3 not found. Install Python 3.11+ and try again."
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)'; then
    err "Python 3.11+ required (found $PY_VER)"
    exit 1
fi
info "Python $PY_VER ✓"

# ── Virtual environment ───────────────────────────────────────────────────────

heading "Setting up virtual environment"

mkdir -p "$DATA_DIR"

if [[ -d "$VENV_DIR" ]]; then
    info "Venv already exists: $VENV_DIR"
else
    if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
        err "Failed to create venv. On Fedora/RHEL, install the venv package:"
        err "  sudo dnf install python3-venv  (or python3X-venv for your version)"
        exit 1
    fi
    info "Created venv: $VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"

# Upgrade pip inside the venv (venv ships its own pip — no system pip needed)
"$VENV_PIP" install --upgrade pip --quiet
info "pip ready ✓"

# ── Install package ───────────────────────────────────────────────────────────

heading "Installing big-brain"

"$VENV_PIP" install -e "$REPO_DIR" --quiet
info "Package installed (editable mode)"

# Create a thin wrapper in ~/.local/bin so 'bb' works from any shell
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/bb" << WRAPPER
#!/usr/bin/env bash
exec "$VENV_DIR/bin/bb" "\$@"
WRAPPER
chmod +x "$BIN_DIR/bb"
info "Wrapper created: $BIN_DIR/bb"

# Warn if ~/.local/bin not in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "~/.local/bin is not in your PATH yet."
    warn "Add to your shell rc and restart:"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    BB_CMD="$VENV_DIR/bin/bb"
else
    BB_CMD="bb"
    info "bb reachable at: $(command -v bb 2>/dev/null || echo "$BIN_DIR/bb")"
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

# If Ollama is running and config still says "noop", switch it automatically
if curl -sf --max-time 2 http://localhost:11434/api/tags &>/dev/null; then
    info "Ollama detected ✓"
    if grep -q 'provider = "noop"' "$CONFIG_FILE"; then
        sed -i 's/^provider = "noop"/provider = "ollama"/' "$CONFIG_FILE"
        info "Switched LLM provider → 'ollama' in config"
    fi

    MODEL="alibayram/Qwen3-30B-A3B-Instruct-2507:latest"
    if curl -sf http://localhost:11434/api/tags | "$VENV_PY" -c "
import json, sys
models = [m['name'] for m in json.load(sys.stdin).get('models', [])]
exit(0 if any('Qwen3-30B' in m for m in models) else 1)
" 2>/dev/null; then
        info "Qwen3-30B-A3B model found ✓"
    else
        warn "Recommended Ollama model not pulled. For best context estimation:"
        warn "  ollama pull $MODEL"
    fi
else
    warn "Ollama not detected — LLM provider left as 'noop'"
    warn "Start Ollama, then re-run this script, or edit $CONFIG_FILE manually"
fi

# ── Shell hook ────────────────────────────────────────────────────────────────

heading "Setting up shell hook (terminal history)"

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
        warn "Unknown shell '$SHELL_NAME' — skipping hook setup"
        warn "Add manually: source \"\$(bb shell-hook-path bash)\""
        ;;
esac

if [[ -n "${RC_FILE:-}" ]]; then
    if grep -q "bb shell-hook-path" "$RC_FILE" 2>/dev/null; then
        info "Shell hook already present in $RC_FILE"
    else
        {
            echo ""
            echo "# big-brain: capture terminal history"
            echo "$HOOK_LINE"
        } >> "$RC_FILE"
        info "Shell hook added to $RC_FILE"
    fi
fi

# ── Daemon ────────────────────────────────────────────────────────────────────

heading "Starting daemon"

PID_FILE="$DATA_DIR/daemon.pid"

_daemon_running() {
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null) || return 1
    kill -0 "$pid" 2>/dev/null
}

if _daemon_running; then
    info "Daemon already running (PID $(cat "$PID_FILE"))"
else
    if "$BB_CMD" daemon start 2>/dev/null; then
        info "Daemon started"
    else
        warn "Could not start daemon automatically."
        warn "Run manually after reloading your shell: bb daemon start"
    fi
fi

# ── MCP server registration ───────────────────────────────────────────────────

heading "Registering MCP server with AI tools"

# Run bb mcp install --client all; it skips clients whose config dirs don't exist
if "$BB_CMD" mcp install --client all 2>/dev/null; then
    : # success messages printed by the command
else
    warn "MCP registration skipped — run manually after setup: bb mcp install"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

RC_DISPLAY="${RC_FILE:-your shell rc file}"
echo ""
echo -e "${BOLD}Installation complete!${NC}"
echo ""
echo "  Reload your shell to activate terminal history:"
echo "    source $RC_DISPLAY"
echo ""
echo "  Quick start:"
echo "    bb add 'first thought'"
echo "    bb search 'thought'"
echo "    bb digest"
echo "    bb llm test"
echo ""
echo "  MCP tools (available in Claude Code, VSCode Copilot, Cursor):"
echo "    search_brain · add_thought · get_recent_context · get_by_date · get_stats"
echo ""
echo "  Config: $CONFIG_FILE"
echo "  Data:   $DATA_DIR"
echo "  Logs:   $DATA_DIR/daemon.log"
echo ""
