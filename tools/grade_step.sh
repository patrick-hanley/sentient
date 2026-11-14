#!/bin/sh
# One graded step: run on the Jetson (brain stopped, then restarted and muted+verified), then append to the ledger (dialog) and /tmp/grade-progress.log.
# Usage: tools/grade_step.sh <label> <tune|held> <toytalk level> <baseline label>      (e.g. v4-level3-tune tune 3 baseline-tune)
set -u
LABEL=$1; SET=$2; LEVEL=$3; BASE=$4
HERE=$(cd "$(dirname "$0")/.." && pwd); PY=${PY:-$HOME/Downloads/sentient/.venv/bin/python}
tools_run="$HERE/tools/grade_remote.sh"
RAW=$LABEL; "$tools_run" "$RAW" "$SET" 1 "$LEVEL" > /tmp/grade-runs/$LABEL.log 2>&1
grep -q "muted-ok" /tmp/grade-runs/$LABEL.log || echo "WARNING: mute not confirmed for $LABEL" >&2
[ -f /tmp/grade-runs/grade-$RAW.json ] || { echo "no result for $LABEL" >&2; exit 1; }
"$PY" "$HERE/tools/grade_ledger.py" add /tmp/grade-runs/grade-$RAW.json --label "$LABEL" --baseline-label "$BASE" --note "${NOTE:-}"
