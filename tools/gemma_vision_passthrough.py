#!/usr/bin/env python3
"""
Laptop-side vision-only passthrough (Wi-Fi): AtomS3R Cam -> Gemma.

Every --interval seconds (default 2):
  1. GET  http://<atoms3r-ip>/capture   -> JPEG frame
  2. Quick check: litert-lm run <gemma .litertlm> --attachment frame.jpg --prompt
     "<check prompt>" -> is anything interesting happening? (YES/NO)
  3. If YES, or if it's been --talk-every seconds (default 60) since the last line
     (so it doesn't go quiet and boring), ask Gemma to react out loud in character
     and print that line.

No TTS, no speak-back, no perception/director stack -- just text reactions
straight from one toy's camera. Useful for a quick "is the vision model noticing
and reacting sensibly" check without running the full brain.

Requires:
  - A toy-client.ino-flashed AtomS3R-CAM whose /capture endpoint is
    reachable at --ip (port 80).
  - litert-lm on PATH and the Gemma .litertlm file at
    ~/.litert-lm/models/gemma4-e2b/model.litertlm (same convention as
    brain/config.py's MODEL_LITERT; override with --model or $SENTIENT_MODEL).

Usage:
  python tools/gemma_vision_passthrough.py --ip 192.168.1.42
  python tools/gemma_vision_passthrough.py --ip 192.168.1.42 --once
  python tools/gemma_vision_passthrough.py --ip 192.168.1.42 --save-frames out/
"""

import argparse
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = Path(os.environ.get("SENTIENT_MODEL", Path.home() / ".litert-lm/models/gemma4-e2b/model.litertlm"))
DEFAULT_PORT = 80
DEFAULT_INTERVAL = 2       # seconds between quick "is this interesting?" checks
DEFAULT_TALK_EVERY = 60    # speak at least this often even if nothing new is happening

CHECK_PROMPT = (
    "You are watching a live toy camera feed. Look at this image and decide whether "
    "anything worth reacting to is happening right now: a person or pet (especially a new "
    "one, a new expression, or a wave/gesture), a new object, motion, or a notable change "
    "from an ordinary still, empty scene. Reply with exactly one word, YES or NO. Nothing else."
)

REACT_PROMPT_TEMPLATE = (
    "You are {name}, {looks}. You are {persona}. "
    "You are looking through your camera right now at whatever is in front of you, like a "
    "warm, friendly toy talking out loud to the child nearby.\n"
    "Look at this image and react to what you actually see in it.\n"
    "Rules:\n"
    "- One short sentence, under 15 words.\n"
    "- Simple, happy, curious words a 2nd-5th grader knows.\n"
    "- Talk about what is really in the picture, not something made up.\n"
    "- If you see a person or pet, greet them warmly by any obvious feature (not a guessed name).\n"
    "- No emojis, no asterisks, no stage directions, just what you'd say out loud."
)

DEFAULT_NAME = "Dyno"
DEFAULT_LOOKS = "a little green dinosaur plush toy"
DEFAULT_PERSONA = "curious and bouncy, easily amazed, and sometimes say a small 'rawr!'"


def capture_frame(ip, port, out_path):
    url = "http://%s:%d/capture" % (ip, port)
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = resp.read()
    out_path.write_bytes(data)
    return data


def ask_gemma(model_path, image_path, prompt):
    result = subprocess.run(
        ["litert-lm", "run", str(model_path), "--attachment", str(image_path), "--prompt", prompt],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def is_interesting(model_path, image_path, check_prompt):
    reply = ask_gemma(model_path, image_path, check_prompt)
    if re.search(r"\byes\b", reply, re.I):
        return True
    if re.search(r"\bno\b", reply, re.I):
        return False
    # Ambiguous reply (model rambled instead of YES/NO) -- err toward reacting.
    return True


def tick(ip, port, model_path, check_prompt, react_prompt, save_dir, last_spoke, talk_every):
    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "frame.jpg"
        frame_bytes = capture_frame(ip, port, frame_path)

        if save_dir:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            (save_dir / f"{stamp}.jpg").write_bytes(frame_bytes)

        ts = datetime.now().strftime("%H:%M:%S")
        interesting = is_interesting(model_path, frame_path, check_prompt)
        overdue = (time.time() - last_spoke) >= talk_every

        if not (interesting or overdue):
            print(f"[{ts}] ({len(frame_bytes)} bytes) ... quiet, nothing new")
            return last_spoke

        reply = ask_gemma(model_path, frame_path, react_prompt)
        why = "interesting" if interesting else "been quiet a while"
        print(f"[{ts}] ({len(frame_bytes)} bytes, {why}) Gemma: {reply}")
        return time.time()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", required=True, help="AtomS3R Cam's IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Path to Gemma .litertlm file")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                         help="Seconds between 'is this interesting?' checks (default: 2)")
    parser.add_argument("--talk-every", type=float, default=DEFAULT_TALK_EVERY,
                         help="Speak at least this often even if nothing new happened (default: 60)")
    parser.add_argument("--check-prompt", default=CHECK_PROMPT, help="Prompt used for the quick YES/NO check")
    parser.add_argument("--name", default=DEFAULT_NAME, help="Character name used in the reaction prompt")
    parser.add_argument("--looks", default=DEFAULT_LOOKS, help="Character description used in the reaction prompt")
    parser.add_argument("--persona", default=DEFAULT_PERSONA, help="Character personality used in the reaction prompt")
    parser.add_argument("--once", action="store_true", help="Run a single iteration and exit")
    parser.add_argument("--save-frames", type=Path, default=None,
                         help="Optional directory to save each captured JPEG into")
    args = parser.parse_args()

    if args.save_frames:
        args.save_frames.mkdir(parents=True, exist_ok=True)

    react_prompt = REACT_PROMPT_TEMPLATE.format(name=args.name, looks=args.looks, persona=args.persona)

    print("Looking at %s:%d every %.0fs (talking at least every %.0fs) ... (Ctrl-C to stop)"
          % (args.ip, args.port, args.interval, args.talk_every))
    last_spoke = time.time()
    try:
        if args.once:
            tick(args.ip, args.port, args.model, args.check_prompt, react_prompt, args.save_frames,
                 0.0, args.talk_every)
        else:
            while True:
                t0 = time.time()
                try:
                    last_spoke = tick(args.ip, args.port, args.model, args.check_prompt, react_prompt,
                                       args.save_frames, last_spoke, args.talk_every)
                except Exception as e:  # noqa: BLE001 -- keep the passthrough alive on a single bad frame
                    print("  (frame skipped:", e, ")")
                time.sleep(max(0, args.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
