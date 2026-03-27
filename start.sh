#!/bin/bash
# Startup script — delegates to scripts/start.sh for production mode.
# For development with hot-reload, use: ./scripts/dev.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/scripts/start.sh"
