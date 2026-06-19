#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/london_daily_debrief.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

"$PYTHON" london_brief_data.py --send-discord >> "$LOG_FILE" 2>&1
