#!/bin/bash
# Install dreamchat CLI, MCP server, and OpenClaw integration.
#
# Usage:
#   cd DREAM-Chat && bash openclaw/setup.sh
#
# What this does:
#   1. Symlinks the dreamchat CLI + MCP server to ~/.local/bin/
#   2. Installs the MCP Python dependency
#   3. Registers the MCP server with OpenClaw (structured tool, no exec needed)
#   4. Copies the OpenClaw skill to ~/.openclaw/skills/dreamchat/
#   5. Injects fallback routing instructions into AGENTS.md
#   6. Runs a quick connectivity check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== DREAM-Chat OpenClaw Integration Setup ==="
echo ""

# --- 1. Install CLI + MCP entry points ---
CLI_SRC="$REPO_DIR/scripts/dreamchat"
MCP_SRC="$REPO_DIR/scripts/dreamchat-mcp"
if [ ! -f "$CLI_SRC" ]; then
    echo "Error: $CLI_SRC not found. Run this from the DREAM-Chat repo root."
    exit 1
fi

# Prefer ~/.local/bin (user-local, no sudo)
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

ln -sf "$CLI_SRC" "$BIN_DIR/dreamchat"
ln -sf "$MCP_SRC" "$BIN_DIR/dreamchat-mcp"
chmod +x "$CLI_SRC" "$MCP_SRC"
echo "[1/6] Linked CLI -> $BIN_DIR/dreamchat"
echo "      Linked MCP -> $BIN_DIR/dreamchat-mcp"

# Check if BIN_DIR is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "     Note: $BIN_DIR is not in your PATH."
    echo "     Add to your shell profile:  export PATH=\"$BIN_DIR:\$PATH\""
fi

# --- 2. Install MCP Python dependency ---
PYTHON_BIN=""
if [ -f "$REPO_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
elif [ -f "$REPO_DIR/venv/bin/python" ]; then
    PYTHON_BIN="$REPO_DIR/venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
fi

if [ -n "$PYTHON_BIN" ]; then
    if "$PYTHON_BIN" -c "import mcp" 2>/dev/null; then
        echo "[2/6] MCP Python SDK already installed."
    else
        echo "[2/6] Installing MCP Python SDK..."
        "$PYTHON_BIN" -m pip install mcp --quiet 2>/dev/null || {
            echo "     Warning: Could not install mcp package. MCP server may not work."
            echo "     Try: pip install mcp"
        }
    fi
else
    echo "[2/6] Warning: No Python found. MCP server requires Python 3.10+."
fi

# --- 3. Register MCP server with OpenClaw ---
MCP_CMD="$BIN_DIR/dreamchat-mcp"

if command -v openclaw &>/dev/null; then
    # Register the MCP server -- OpenClaw spawns it on demand over stdio
    # env.no_proxy ensures the server connects to localhost directly, not through a proxy
    MCP_PYTHON="$PYTHON_BIN"
    MCP_CONFIG="{\"command\":\"$MCP_PYTHON\",\"args\":[\"$REPO_DIR/scripts/dreamchat-mcp\"],\"timeout\":120000,\"env\":{\"no_proxy\":\"localhost,127.0.0.1\",\"NO_PROXY\":\"localhost,127.0.0.1\"}}"
    openclaw mcp set dreamchat-health "$MCP_CONFIG" 2>/dev/null && \
        echo "[3/6] Registered MCP server: dreamchat-health" || \
        echo "[3/6] Warning: Could not register MCP server. Run manually:"
    echo "      openclaw mcp set dreamchat-health '$MCP_CONFIG'"
else
    echo "[3/6] Skipped MCP registration (openclaw not found in PATH)."
    echo "     After installing OpenClaw, run:"
    echo "     openclaw mcp set dreamchat-health '{\"command\":\"$MCP_CMD\"}'"
fi

# --- 4. Install OpenClaw skill ---
SKILL_SRC="$SCRIPT_DIR/skills/dreamchat/SKILL.md"
SKILL_DST="$HOME/.openclaw/skills/dreamchat"

if [ -d "$HOME/.openclaw" ]; then
    mkdir -p "$SKILL_DST"
    cp "$SKILL_SRC" "$SKILL_DST/SKILL.md"
    echo "[4/6] Installed OpenClaw skill -> $SKILL_DST/SKILL.md"
else
    echo "[4/6] Skipped OpenClaw skill (no ~/.openclaw/ directory found)."
    echo "     Install OpenClaw first, then re-run this script."
fi

# --- 5. Inject AGENTS.md routing section (fallback for skill bug #49873) ---
AGENTS_SECTION="$SCRIPT_DIR/agents-section.md"
AGENTS_MD="$HOME/.openclaw/workspace/AGENTS.md"

if [ -d "$HOME/.openclaw" ]; then
    mkdir -p "$HOME/.openclaw/workspace"

    SECTION_HEADER="## DreamChat Health System (MANDATORY)"

    if [ -f "$AGENTS_MD" ] && grep -qF "$SECTION_HEADER" "$AGENTS_MD"; then
        # Replace existing section
        awk -v header="$SECTION_HEADER" -v section_file="$AGENTS_SECTION" '
        BEGIN { skipping = 0; injected = 0 }
        $0 == header {
            skipping = 1
            while ((getline line < section_file) > 0) print line
            close(section_file)
            injected = 1
            next
        }
        skipping && /^## / && $0 != header {
            skipping = 0
        }
        !skipping { print }
        ' "$AGENTS_MD" > "${AGENTS_MD}.tmp"
        mv "${AGENTS_MD}.tmp" "$AGENTS_MD"
        echo "[5/6] Updated DreamChat section in $AGENTS_MD"
    elif [ -f "$AGENTS_MD" ]; then
        echo "" >> "$AGENTS_MD"
        cat "$AGENTS_SECTION" >> "$AGENTS_MD"
        echo "[5/6] Appended DreamChat section to $AGENTS_MD"
    else
        cp "$AGENTS_SECTION" "$AGENTS_MD"
        echo "[5/6] Created $AGENTS_MD with DreamChat section"
    fi
else
    echo "[5/6] Skipped AGENTS.md injection (no ~/.openclaw/ directory found)."
fi

# --- 6. Verify ---
echo "[6/6] Checking connectivity..."
if command -v dreamchat &>/dev/null || [ -x "$BIN_DIR/dreamchat" ]; then
    "$BIN_DIR/dreamchat" --json server status 2>/dev/null && echo "     Server is reachable." || echo "     Server not running. Start DREAM-Chat first: python app.py"
else
    echo "     dreamchat not found in PATH. Add $BIN_DIR to PATH and try again."
fi

echo ""
echo "Setup complete!"
echo ""
echo "What was installed:"
echo "  - dreamchat CLI       (for scripting and debugging)"
echo "  - dreamchat-mcp       (MCP server -- OpenClaw calls this directly)"
echo "  - AGENTS.md section   (fallback instructions for the agent)"
echo "  - SKILL.md            (skill documentation)"
echo ""
echo "The MCP server gives OpenClaw a structured 'health_ask' tool."
echo "The agent calls it directly -- no shell exec, no approval prompts."
echo ""
echo "Next steps:"
echo "  1. Start DREAM-Chat:  python app.py"
echo "  2. Configure CLI:     dreamchat configure"
echo "  3. Test MCP:          echo '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}' | dreamchat-mcp"
echo "  4. Restart gateway:   openclaw gateway stop && openclaw gateway start"
