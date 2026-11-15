#!/bin/sh
# Run the toy-to-toy grading on the Jetson WITHOUT touching the live brain code: the worktree is rsynced to /data/sentient-grade (a copy),
# sentient-brain is stopped for the run (Gemma and the brain do not both fit in RAM), and afterwards restarted and muted straight away.
# Usage: [GRADE_ENV="SENTIENT_X=1 ..."] tools/grade_remote.sh <label> <tune|held> [reps] [toytalk level]      (needs the user's OK that the Jetson is free: the 'aec' goal also uses it)
set -u
LABEL=${1:?label}; SET=${2:-tune}; REPS=${3:-1}; TT=${4:-0}
HOST=sentient@sentient-jetson.local; DEST=/data/sentient-grade
HERE=$(cd "$(dirname "$0")/.." && pwd)
rsync -a --delete --exclude .venv --exclude __pycache__ --exclude offline --exclude data "$HERE/brain" "$HERE/tools" $HOST:$DEST/ 2>/dev/null || { ssh $HOST "mkdir -p $DEST" && rsync -a --exclude __pycache__ "$HERE/brain" "$HERE/tools" $HOST:$DEST/; }
ssh $HOST "sudo systemctl stop sentient-brain; cd $DEST && ${GRADE_ENV:-} PYTHONPATH=$DEST /data/sentient/.venv-brain/bin/python tools/grade_toys.py run --model litert --set $SET --reps $REPS --toytalk $TT --label $LABEL --out /tmp/grade-$LABEL.json --agg-out /tmp/grade-$LABEL.agg.json"
RC=$?
ssh $HOST "sudo systemctl start sentient-brain"
# the live brain's /mute may be a bare toggle (older build): only POST when the state says it is not muted, then verify. Ends muted or fails loudly.
ssh $HOST 'for i in $(seq 1 120); do if curl -sf localhost:8080/state 2>/dev/null | grep -q "\"muted\": true"; then echo muted-ok; exit 0; fi; curl -sf -X POST "localhost:8080/mute?on=1" >/dev/null 2>&1; sleep 0.5; done; echo MUTE-FAILED; exit 1' || { echo "MUTE-FAILED: mute the brain by hand"; RC=1; }
mkdir -p /tmp/grade-runs && scp $HOST:/tmp/grade-$LABEL.json $HOST:/tmp/grade-$LABEL.agg.json /tmp/grade-runs/ 2>/dev/null
exit $RC
