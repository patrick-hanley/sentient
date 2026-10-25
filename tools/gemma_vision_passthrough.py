#!/usr/bin/env python3
"""
Laptop-side vision-only passthrough (Wi-Fi): AtomS3R Cam -> Gemma.

Every --interval seconds (default 60 = 1 minute):
  1. GET  http://<atoms3r-ip>/capture   -> JPEG frame
  2. litert-lm run <gemma .litertlm> --attachment frame.jpg --prompt
     "Describe what you see in one short, natural sentence."  -> text
  3. Print the frame size + Gemma's reply to the console.

No TTS, no speak-back, no perception/director stack -- just text captions
straight from one toy's camera. Useful for a quick "is the vision model
seeing anything sensible" check without running the full brain.

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
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = Path(os.environ.get("SENTIENT_MODEL", Path.home() / ".litert-lm/models/gemma4-e2b/model.litertlm"))
DEFAULT_PROMPT = "Describe what you see in one short, natural sentence."
DEFAULT_PORT = 80
DEFAULT_INTERVAL = 60  # seconds


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


def look(ip, port, model_path, prompt, save_dir):
    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "frame.jpg"
        frame_bytes = capture_frame(ip, port, frame_path)

        if save_dir:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            (save_dir / f"{stamp}.jpg").write_bytes(frame_bytes)

        reply = ask_gemma(model_path, frame_path, prompt)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] ({len(frame_bytes)} bytes) Gemma: {reply}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", required=True, help="AtomS3R Cam's IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Path to Gemma .litertlm file")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                         help="Seconds between captures (default: 60 = 1 minute)")
    parser.add_argument("--once", action="store_true", help="Run a single iteration and exit")
    parser.add_argument("--save-frames", type=Path, default=None,
                         help="Optional directory to save each captured JPEG into")
    args = parser.parse_args()

    if args.save_frames:
        args.save_frames.mkdir(parents=True, exist_ok=True)

    print("Looking at %s:%d every %.0fs ... (Ctrl-C to stop)" % (args.ip, args.port, args.interval))
    try:
        if args.once:
            look(args.ip, args.port, args.model, args.prompt, args.save_frames)
        else:
            while True:
                t0 = time.time()
                try:
                    look(args.ip, args.port, args.model, args.prompt, args.save_frames)
                except Exception as e:  # noqa: BLE001 -- keep the passthrough alive on a single bad frame
                    print("  (frame skipped:", e, ")")
                time.sleep(max(0, args.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
