#!/bin/bash
# Install dreamchat CLI and OpenClaw skill.
#
# Usage:
#   cd DREAM-Chat && bash openclaw/setup.sh
#
# What this does:
#   1. Symlinks the dreamchat CLI to ~/.local/bin/ (or /usr/local/bin/)
#   2. Copies the OpenClaw skill to ~/.openclaw/skills/dreamchat/
#   3. Runs a quick connectivity check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== DREAM-Chat OpenClaw Integration Setup ==="
echo ""

# --- 1. Install CLI ---
CLI_SRC="$REPO_DIR/scripts/dreamchat"
if [ ! -f "$CLI_SRC" ]; then
    echo "Error: $CLI_SRC not found. Run this from the DREAM-Chat repo root."
    exit 1
fi

# Prefer ~/.local/bin (user-local, no sudo)
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

ln -sf "$CLI_SRC" "$BIN_DIR/dreamchat"
chmod +x "$CLI_SRC"
echo "[1/3] Linked dreamchat CLI -> $BIN_DIR/dreamchat"

# Check if BIN_DIR is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "     Note: $BIN_DIR is not in your PATH."
    echo "     Add to your shell profile:  export PATH=\"$BIN_DIR:\$PATH\""
fi

# --- 2. Install OpenClaw skill ---
SKILL_SRC="$SCRIPT_DIR/skills/dreamchat/SKILL.md"
SKILL_DST="$HOME/.openclaw/skills/dreamchat"

if [ -d "$HOME/.openclaw" ]; then
    mkdir -p "$SKILL_DST"
    cp "$SKILL_SRC" "$SKILL_DST/SKILL.md"
    echo "[2/3] Installed OpenClaw skill -> $SKILL_DST/SKILL.md"
else
    echo "[2/3] Skipped OpenClaw skill (no ~/.openclaw/ directory found)."
    echo "     Install OpenClaw first, then re-run this script."
fi

# --- 3. Verify ---
echo "[3/3] Checking connectivity..."
if command -v dreamchat &>/dev/null || [ -x "$BIN_DIR/dreamchat" ]; then
    "$BIN_DIR/dreamchat" --json server status 2>/dev/null && echo "     Server is reachable." || echo "     Server not running. Start DREAM-Chat first: python app.py"
else
    echo "     dreamchat not found in PATH. Add $BIN_DIR to PATH and try again."
fi

echo ""
echo "Setup complete. Next steps:"
echo "  1. Start DREAM-Chat:  python app.py"
echo "  2. Configure CLI:     dreamchat configure"
echo "  3. Test:              dreamchat --json server status"
echo "  4. Try it:            dreamchat --json health status"
