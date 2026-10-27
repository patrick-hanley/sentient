#!/usr/bin/env python3
"""Push a firmware image to Atoms over Wi-Fi (firmware toy-client-3.4+ with OTA_TOKEN in secrets.h).

  python tools/ota.py --ssh sentient@192.168.2.5 [--bin build/toy-client.ino.bin] [--atom 10.42.0.236 ...]

The Atoms live on the Pi's hotspot (10.42.0.x), which the Mac cannot reach directly, so --ssh pipes the image through the
Pi (curl runs there). Without --ssh the Atoms are contacted directly (run it on the Pi, or when the Mac shares their network).

Atom IPs come from the brain dashboard (/state) unless --atom is given. Build the image with:
  arduino-cli compile -b m5stack:esp32:m5stack_atoms3r:CDCOnBoot=cdc,PSRAM=opi --build-path build firmware/toy-client
Each Atom checks the token, writes its spare app slot, verifies the image, reboots, and must come back reporting the
new fw version in /status; a failed or interrupted update leaves the old image running. Clips in flash are untouched.
"""
import argparse
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def token():
    m = re.search(r'#define\s+OTA_TOKEN\s+"([^"]+)"', (ROOT / "firmware/toy-client/secrets.h").read_text())
    if not m:
        raise SystemExit("no OTA_TOKEN in firmware/toy-client/secrets.h")
    return m.group(1)


SSH = None


def via_pi(cmd, stdin=None, timeout=150):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", SSH, cmd], input=stdin, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode(errors="replace").strip(), r.stderr.decode(errors="replace").strip()


def status(ip):
    if SSH:
        rc, out, err = via_pi(f"curl -s -m 3 http://{ip}/status")
        if rc or not out:
            raise OSError(err or "no answer")
        return json.loads(out)
    with opener.open(f"http://{ip}/status", timeout=3) as r:
        return json.loads(r.read())


def push(ip, image, tok):
    if SSH:
        rc, out, err = via_pi(f"curl -s -m 120 -f -X POST -H 'X-OTA-Token: {tok}' -H 'Content-Type: application/octet-stream' "
                              f"--data-binary @- http://{ip}/update", stdin=image)
        if rc:
            raise OSError(f"curl exit {rc} {err}")
        return out
    req = urllib.request.Request(f"http://{ip}/update", data=image, method="POST",
                                 headers={"X-OTA-Token": tok, "Content-Type": "application/octet-stream"})
    with opener.open(req, timeout=120) as r:
        return r.read().decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default="/private/tmp/claude-501/fwbuild/toy-client.ino.bin")
    ap.add_argument("--brain", default="192.168.2.5")
    ap.add_argument("--atom", action="append", default=[])
    ap.add_argument("--ssh", help="user@pi: reach the Atoms through the Pi")
    ap.add_argument("--version", help="expected fw string afterwards (default: read from the sketch)")
    a = ap.parse_args()
    global SSH
    SSH = a.ssh
    want = a.version or re.search(r'FW_VERSION\s*=\s*"([^"]+)"', (ROOT / "firmware/toy-client/toy-client.ino").read_text()).group(1)
    ips = a.atom
    if not ips:
        raw = via_pi("curl -s http://127.0.0.1:8080/state")[1] if SSH else opener.open(f"http://{a.brain}:8080/state", timeout=5).read()
        st = json.loads(raw)
        ips = [t["ip"] for t in st["toys"].values() if t["online"] and t["ip"]]
    image, tok = Path(a.bin).read_bytes(), token()
    print(f"{len(image) // 1024} KB image, target fw {want}, atoms {ips}")
    for ip in ips:
        before = status(ip)["fw"]
        try:
            print(f"{ip}: {before} -> {push(ip, image, tok)}")
        except Exception as e:  # noqa: BLE001
            print(f"{ip}: FAILED ({e}); still running {before}")
            continue
        for _ in range(30):
            time.sleep(2)
            try:
                fw = status(ip)["fw"]
                print(f"{ip}: back up on {fw}" + ("" if fw == want else "  <-- NOT the expected version"))
                break
            except Exception:  # noqa: BLE001
                pass
        else:
            print(f"{ip}: did not come back within 60 s")


if __name__ == "__main__":
    main()
