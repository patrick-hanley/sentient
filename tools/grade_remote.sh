#!/bin/sh
# Run the toy-to-toy grading on the Jetson WITHOUT touching the live brain code: the worktree is rsynced to /data/sentient-grade (a copy),
# sentient-brain is stopped for the run (Gemma and the brain do not both fit in RAM), and afterwards restarted and muted straight away.
# Usage: tools/grade_remote.sh <label> <tune|held> [reps]      (needs the user's OK that the Jetson is free: the 'aec' goal also uses it)
set -u
LABEL=${1:?label}; SET=${2:-tune}; REPS=${3:-1}
HOST=sentient@sentient-jetson.local; DEST=/data/sentient-grade
HERE=$(cd "$(dirname "$0")/.." && pwd)
rsync -a --delete --exclude .venv --exclude __pycache__ --exclude offline "$HERE/brain" "$HERE/tools" $HOST:$DEST/ 2>/dev/null || { ssh $HOST "mkdir -p $DEST" && rsync -a --exclude __pycache__ "$HERE/brain" "$HERE/tools" $HOST:$DEST/; }
ssh $HOST "sudo systemctl stop sentient-brain; cd $DEST && PYTHONPATH=$DEST /data/sentient/.venv-brain/bin/python tools/grade_toys.py run --model litert --set $SET --reps $REPS --label $LABEL --out /tmp/grade-$LABEL.json --agg-out /tmp/grade-$LABEL.agg.json"
RC=$?
ssh $HOST "sudo systemctl start sentient-brain"
sleep 20; ssh $HOST "curl -s -X POST localhost:8080/mute"
mkdir -p /tmp/grade-runs && scp $HOST:/tmp/grade-$LABEL.json $HOST:/tmp/grade-$LABEL.agg.json /tmp/grade-runs/ 2>/dev/null
exit $RC
