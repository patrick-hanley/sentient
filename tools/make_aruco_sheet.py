"""Print sheet: ArUco DICT_4X4_50 tags for the toys (id 1 Dyno, 2 Sage, 3 Penny).

US Letter at 300 DPI, 4 cm tags with a white border, two of each (spares).
Print at 100% / "Actual size" — not "Fit to page".
Usage: python tools/make_aruco_sheet.py [out.png]
"""
import sys
import cv2
import numpy as np

DPI = 300
CM = DPI / 2.54
TOYS = [(1, "DYNO"), (2, "SAGE"), (3, "PENNY")]
TAG = int(4 * CM)          # 4 cm black square
PAD = int(0.8 * CM)        # white quiet zone around each tag

out = sys.argv[1] if len(sys.argv) > 1 else "aruco_sheet.png"
page = np.full((11 * DPI, int(8.5 * DPI)), 255, np.uint8)
d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

cell_w, cell_h = TAG + 2 * PAD, TAG + 2 * PAD + int(1.2 * CM)
x0, y0 = int(0.6 * DPI), int(0.8 * DPI)
for row, (tid, name) in enumerate(TOYS):
    for col in range(2):
        x, y = x0 + col * (cell_w + int(0.5 * DPI)), y0 + row * (cell_h + int(0.25 * DPI))
        cv2.rectangle(page, (x, y), (x + cell_w, y + cell_h), 200, 2)  # cut line
        page[y + PAD:y + PAD + TAG, x + PAD:x + PAD + TAG] = cv2.aruco.generateImageMarker(d, tid, TAG)
        cv2.putText(page, f"{name}  (id {tid})", (x + PAD, y + 2 * PAD + TAG + int(0.4 * CM)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
cv2.putText(page, "Sentient toys - print at 100% (actual size). Keep the white border when cutting.",
            (x0, int(0.45 * DPI)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2)
cv2.imwrite(out, page)

# Self-check: the sheet must detect all six tags.
det = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
_, ids, _ = det.detectMarkers(page)
print(out, "detected ids:", sorted(ids.flatten().tolist()) if ids is not None else None)
