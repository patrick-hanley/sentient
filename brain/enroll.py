"""Enroll family faces and pets (embeddings only, stored in brain/data/enroll.npz).

  python -m brain.enroll --from-dir enroll/            # enroll/people/<Name>/*.jpg, enroll/pets/<Name>/*.jpg
  python -m brain.enroll --live --toy sage --name Patrick   # needs the brain NOT running (or use dashboard)
  python -m brain.enroll --list | --forget NAME | --wipe
Photos: 3–5 per person/pet, clear, front-facing. Delete enroll.npz after the event.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import cv2
import numpy as np

from . import config
from .perception import PET_CLASSES, Recognizer


def largest_face(rec, img):
    faces = rec.faces(img)
    return max(faces, key=lambda f: f[0][2] * f[0][3]) if faces else None


def enroll_person(rec, name, imgs) -> int:
    n = 0
    for img in imgs:
        f = largest_face(rec, img)
        if f:
            rec.people.setdefault(name, []).append(f[1])
            n += 1
    return n


def enroll_pet(rec, name, imgs) -> int:
    n = 0
    for img in imgs:
        dets = [d for d in rec.objects(img) if d[0] in PET_CLASSES]
        if not dets:
            continue
        cls, box, _ = max(dets, key=lambda d: d[1][2] * d[1][3])
        vec = rec.embed(img, box)
        species, feats = rec.pets.get(name, (cls, []))
        if vec is not None:
            feats.append(vec)
        rec.pets[name] = (species, feats)
        n += 1
    return n


def load_imgs(folder: Path):
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".webp"):
            img = cv2.imread(str(p))
            if img is None:
                print(f"  can't read {p.name} (HEIC? export as JPEG)")
                continue
            s = 640 / max(img.shape[:2])
            yield cv2.resize(img, None, fx=s, fy=s) if s < 1 else img


def main():
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", type=Path)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--toy", default="sage")
    ap.add_argument("--name")
    ap.add_argument("--pet", action="store_true", help="live-enroll a pet instead of a face")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--forget")
    ap.add_argument("--wipe", action="store_true")
    a = ap.parse_args()
    rec = Recognizer()
    if a.wipe:
        config.ENROLL_DB.unlink(missing_ok=True)
        print("wiped")
        return
    if a.forget:
        rec.people.pop(a.forget, None)
        rec.pets.pop(a.forget, None)
    if a.from_dir:
        for kind, fn in (("people", enroll_person), ("pets", enroll_pet)):
            for d in sorted((a.from_dir / kind).glob("*")):
                if d.is_dir():
                    print(f"{kind}/{d.name}: {fn(rec, d.name, list(load_imgs(d)))} photo(s) enrolled")
    if a.live:
        from .atoms import AtomHub
        hub = AtomHub(on_audio=lambda *_: None)
        hub.start()
        print(f"waiting for {a.toy}…")
        while a.toy not in hub.online():
            time.sleep(0.5)
        imgs = []
        for i in range(8):
            jpg = hub.capture(a.toy)
            if jpg:
                imgs.append(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR))
            time.sleep(0.4)
        n = (enroll_pet if a.pet else enroll_person)(rec, a.name, imgs)
        print(f"{a.name}: {n}/{len(imgs)} frames enrolled")
    if a.from_dir or a.live or a.forget:
        rec.save_db()
    print("people:", {k: len(v) for k, v in rec.people.items()}, "pets:", {k: (v[0], len(v[1])) for k, v in rec.pets.items()})


if __name__ == "__main__":
    main()
