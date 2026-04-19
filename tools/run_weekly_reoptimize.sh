#!/usr/bin/env bash
# Wrapper for weekly_reoptimize.py with unbuffered + timestamped logging.
#
# Works for both cron (unattended) and ad-hoc manual runs — child output is
# line-timestamped and appended to data/reoptimize.log, and also echoed to the
# calling terminal via `tee` for interactive visibility.
#
# Usage:
#   bash tools/run_weekly_reoptimize.sh                       # full pipeline
#   bash tools/run_weekly_reoptimize.sh --strategy support    # pass-through args
#   bash tools/run_weekly_reoptimize.sh --dry-run --no-email
#
# Cron:
#   0 10 * * 6 bash /Users/kamenkamenov/agentic-trading/tools/run_weekly_reoptimize.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

LOG_FILE="$REPO_DIR/data/reoptimize.log"

# Prefer the pinned Python 3.10 used by the rest of the trading stack;
# fall back to whatever python3 is on PATH.
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

# Use moreutils `ts` if installed, else the bundled Python fallback.
if command -v ts >/dev/null 2>&1; then
    TIMESTAMPER=(ts '[%Y-%m-%d %H:%M:%S]')
else
    TIMESTAMPER=("$PYTHON_BIN" -u "$SCRIPT_DIR/_log_ts.py")
fi

# `python3 -u` disables stdout/stderr buffering inside the orchestrator so
# every `print()` (including non-flushed ones) reaches the pipe immediately.
# `2>&1` merges stderr so the timestamper sees both streams.
# `tee -a` appends to the log AND echoes live for interactive manual runs.
# `pipefail` (set above) propagates the orchestrator's exit code through the pipe.
"$PYTHON_BIN" -u tools/weekly_reoptimize.py "$@" 2>&1 \
    | "${TIMESTAMPER[@]}" \
    | tee -a "$LOG_FILE"
