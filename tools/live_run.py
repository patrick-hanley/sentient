"""Live A/B on the real toys: the Mac speaks kid questions near them, then we read the brain's turn log.

  python tools/live_run.py --brain 192.168.2.5 --label kitten --n 8
Prints p50/max of: filler audible, real reply audible on the Atom, silence between toys, whole turn.
Switch voices on the dashboard (or POST /voice) between runs. Idle chatter is paused during a run.
"""
import argparse
import json
import statistics
import subprocess
import time
import urllib.request

PROMPTS = ["What is seven times eight?", "Why is the sky blue?", "How do you spell because?",
           "What is the biggest planet?", "Can you tell me a riddle?", "What is the capital of Texas?",
           "How do plants grow?", "What is half of twenty?", "Why do birds fly south?", "Can we play twenty questions?"]


def get(base, path, post=False):
    req = urllib.request.Request(f"http://{base}:8080{path}", data=b"" if post else None, method="POST" if post else "GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read()
    try:
        return json.loads(body or b"null")
    except ValueError:   # toggles reply with plain text
        return body.decode()


def stats(vals, ms=False):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "n/a"
    if ms:
        return f"p50 {statistics.median(vals):.0f}ms  max {max(vals):.0f}ms  (n={len(vals)})"
    return f"p50 {statistics.median(vals) / 1000:.1f}s  max {max(vals) / 1000:.1f}s  (n={len(vals)})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default="192.168.2.5")
    ap.add_argument("--label", default="run")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--voice", default="Samantha")
    ap.add_argument("--atom", help="play the questions through this toy's speaker (via ssh to the Pi) instead of the Mac's")
    ap.add_argument("--ssh", default="sentient@192.168.2.5")
    a = ap.parse_args()
    idle_was_on = get(a.brain, "/state")["idle"]
    if idle_was_on:
        get(a.brain, "/idle", post=True)
    try:
        time.sleep(8)   # let any idle turn finish
        rows = []
        if a.atom:
            import os, tempfile
            tmp = tempfile.mkdtemp()
            for i in range(min(a.n, len(PROMPTS))):
                subprocess.run(["say", "-v", a.voice, "-o", f"{tmp}/{i}.aiff", PROMPTS[i]], check=True)
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", f"{tmp}/{i}.aiff", f"{tmp}/{i}.wav"], check=True)
            subprocess.run(["ssh", a.ssh, "mkdir -p /tmp/asks"], check=True)
            subprocess.run(["scp", "-q", *[f"{tmp}/{i}.wav" for i in range(min(a.n, len(PROMPTS)))], f"{a.ssh}:/tmp/asks/"], check=True)
        for i in range(a.n):
            seen = max([t["turn_id"] for t in get(a.brain, "/latency")["turns"]] or [0])
            if a.atom:
                subprocess.run(["ssh", a.ssh, f"cd /data/sentient && .venv-brain/bin/python tools/atom_ask.py {a.atom} /tmp/asks/{i % len(PROMPTS)}.wav"], check=True)
            else:
                subprocess.run(["say", "-v", a.voice, PROMPTS[i % len(PROMPTS)]], check=True)
            end = time.time() + 60
            got = None
            while time.time() < end and not got:
                time.sleep(1.5)
                new = [t for t in get(a.brain, "/latency")["turns"] if t["turn_id"] > seen and t["source"].startswith("speech")]
                got = new[0] if new and new[0]["status"] in ("ok", "failed") else None
            if got:
                rows.append(got)
                m, w = got["milestones_ms"], got["stage_work_ms"]
                print(f"turn {got['turn_id']}: filler {m.get('atom_first_sample_ms')} reply {m.get('atom_reply_sample_ms')} "
                      f"gap {w.get('handoff_gap_ms')} done {m.get('turn_done_ms')}", flush=True)
            else:
                print("turn not heard (toys too far from the Mac speaker?)", flush=True)
            time.sleep(4)
    finally:
        if idle_was_on:
            get(a.brain, "/idle", post=True)
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"\n== {a.label}: {len(ok)} ok of {a.n} ==")
    print("filler audible       ", stats([r["milestones_ms"].get("atom_first_sample_ms") for r in ok]))
    print("real reply audible   ", stats([r["milestones_ms"].get("atom_reply_sample_ms") for r in ok]))
    print("worst silence between toys", stats([r["stage_work_ms"].get("handoff_gap_max_ms") for r in ok], ms=True))
    print("whole turn           ", stats([r["milestones_ms"].get("turn_done_ms") for r in ok]))
    print("tts work (sum)       ", stats([r["stage_work_ms"].get("tts_ms") for r in ok]))


if __name__ == "__main__":
    main()
