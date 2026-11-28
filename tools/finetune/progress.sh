#!/bin/sh
# Show a training run's progress lines, posted by train_lora.py --progress https://ntfy.sh/<topic>.
# Usage: progress.sh [topic] [since]   (since: 2h, 30m, all; default 12h). The topic is read from .progress-topic if not given.
# Reading it needs no Google sign-in and works whether the notebook tab is open or not.
cd "$(dirname "$0")"
topic=${1:-$(cat .progress-topic 2>/dev/null)}
[ -n "$topic" ] || { echo "no topic: pass one or put it in tools/finetune/.progress-topic"; exit 1; }
curl -s "https://ntfy.sh/$topic/json?poll=1&since=${2:-12h}" | python3 -c '
import json, sys, time
rows = [json.loads(l) for l in sys.stdin if l.strip()]
rows = [r for r in rows if r.get("event") == "message"]
for r in rows:
    print(time.strftime("%H:%M", time.localtime(r["time"])), r["message"])
if rows:
    age = (time.time() - rows[-1]["time"]) / 60
    print(f"-- last line {age:.0f} min ago" + ("  (over 10 min with no line: the run may have stopped)" if age > 10 and "saved" not in rows[-1]["message"] else ""))
else:
    print("-- nothing posted yet")
'
