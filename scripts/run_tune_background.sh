#!/bin/bash
# Long-running game-EPA weight tuning (2018-2025).
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="output/tune_game_epa.log"
PID_FILE="output/tune_game_epa.pid"

echo "=== BCPI tune started $(date) ===" >> "$LOG"

.venv/bin/python -u run_bcpi.py tune \
  --start 2018 \
  --end 2025 \
  --samples 80 \
  --refine 50 >> "$LOG" 2>&1

echo "=== BCPI tune finished $(date) ===" >> "$LOG"
