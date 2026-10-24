"""Can the toys' 320x240 cameras read price-tag barcodes? Polls every toy's /capture and decodes.

Usage: python tools/barcode_test.py [seconds]   (brain must be running; uses its toy list)
"""
import json
import sys
import time
import urllib.request

import cv2
import numpy as np

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 40
toys = {k: v["ip"] for k, v in json.load(urllib.request.urlopen("http://localhost:8080/state"))["toys"].items() if v["online"]}
det = cv2.barcode.BarcodeDetector()
end = time.time() + DUR
hits, found = {}, {}
while time.time() < end:
    for toy, ip in toys.items():
        try:
            jpg = urllib.request.urlopen(f"http://{ip}/capture", timeout=3).read()
        except OSError:
            continue
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
        for scale in (1, 2):
            im = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale > 1 else img
            ok, infos, types, pts = det.detectAndDecode(im)[:4] if len(det.detectAndDecode(im)) >= 4 else (False, [], [], None)
            res = det.detectAndDecodeWithType(im) if hasattr(det, "detectAndDecodeWithType") else None
            texts = [t for t in (res[1] if res else infos) if t]
            located = res[0] if res else ok
            if located and not texts:
                found[toy] = found.get(toy, 0) + 1
            for t in texts:
                key = (toy, t, f"x{scale}")
                if key not in hits:
                    print(f"{time.strftime('%H:%M:%S')} {toy}: decoded {t} (upscale x{scale})", flush=True)
                hits[key] = hits.get(key, 0) + 1
            if texts:
                break
    time.sleep(0.2)
print("decoded:", {f"{k[0]}:{k[1]}:{k[2]}": v for k, v in hits.items()} or "nothing")
print("located-but-not-decoded frames:", found or "none")
