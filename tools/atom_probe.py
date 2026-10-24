"""Mac-side Atom test: acts as a minimal brain for toy-client firmware.

- answers HELLO with ACK, lists toys (MAC, IP, cam/mic/spk flags)
- prints a live mic level bar per toy (talk at it — the bar should jump)
- saves one /capture JPEG per toy to probe_<mac>.jpg
- plays a 1 s two-tone chirp through each toy's /play

Usage: .venv/bin/python -I tools/atom_probe.py [seconds=25]
Mac firewall: allow incoming for Python if prompted.
"""
import math, socket, struct, sys, threading, time, urllib.request
import numpy as np

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 25
toys = {}  # ip -> dict
lock = threading.Lock()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", 5005))
sock.settimeout(0.5)

def chirp():
    t = np.arange(16000) / 16000
    f = np.where(t < 0.5, 660, 880)
    return (0.4 * 32767 * np.sin(2 * np.pi * f * t) * np.minimum(1, (1 - t) * 20)).astype("<i2").tobytes()

def probe(ip):
    mac = toys[ip]["mac"].replace(":", "")
    try:
        print(f"[{ip}] status:", urllib.request.urlopen(f"http://{ip}/status", timeout=3).read().decode())
    except Exception as e:
        print(f"[{ip}] status FAILED: {e}")
    try:
        jpg = urllib.request.urlopen(f"http://{ip}/capture", timeout=5).read()
        open(f"probe_{mac}.jpg", "wb").write(jpg)
        print(f"[{ip}] capture OK: probe_{mac}.jpg ({len(jpg)} bytes)")
    except Exception as e:
        print(f"[{ip}] capture FAILED: {e}")
    try:
        req = urllib.request.Request(f"http://{ip}/play", data=chirp(), method="POST",
                                     headers={"Content-Type": "application/octet-stream"})
        print(f"[{ip}] play:", urllib.request.urlopen(req, timeout=10).read().decode(), "(listen for a chirp)")
    except Exception as e:
        print(f"[{ip}] play FAILED: {e}")

end = time.time() + DUR
last_print = 0
print(f"Listening on UDP 5005 for {DUR:.0f}s… (Atoms must be on the same Wi-Fi as this Mac)")
while time.time() < end:
    try:
        data, (ip, _) = sock.recvfrom(2048)
    except socket.timeout:
        continue
    if data.startswith(b"HELLO"):
        parts = data.decode(errors="replace").split()
        new = ip not in toys
        toys.setdefault(ip, {"mac": parts[1], "rms": 0.0, "pkts": 0})
        toys[ip]["hello"] = " ".join(parts[2:])
        sock.sendto(b"ACK", (ip, 5006))
        if new:
            print(f"NEW TOY {parts[1]} at {ip}: {' '.join(parts[2:])}")
            threading.Thread(target=probe, args=(ip,), daemon=True).start()
    elif data[:1] == b"M" and ip in toys:
        s = np.frombuffer(data[3:], "<i2").astype(np.float32)
        toys[ip]["rms"] = 0.8 * toys[ip]["rms"] + 0.2 * float(np.sqrt(np.mean(s * s)))
        toys[ip]["pkts"] += 1
    elif ip in toys:
        print(f"[{ip}] {data.decode(errors='replace')}")
    if time.time() - last_print > 0.5 and toys:
        last_print = time.time()
        line = "  ".join(f"{t['mac'][-5:]} {'#' * min(30, int(t['rms'] / 100)):<30} {t['pkts']:5d}pk"
                         for t in toys.values())
        print("\rMIC " + line, end="", flush=True)
print("\nDone. Toys seen:", {ip: t["mac"] for ip, t in toys.items()})
