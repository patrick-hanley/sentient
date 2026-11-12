"""Teach the camera: parents, the child, each toy's own look, and household items, by name, from the Parent Board.

Privacy rules (docs/vision.md):
  * a parent must give explicit consent for every enrollment (recorded as a date, never the photo);
  * EMBEDDINGS ONLY: photos are decoded in RAM, turned into vectors and dropped; no image is ever written;
  * the vectors are encrypted with the Parent Board's key (AES-GCM, same file format and key as the profiles, file
    teach.enc). While the board is locked (after a restart until a parent enters the PIN) nothing is enrolled: unknown
    faces are just "a person" and the toys cannot tell who is who;
  * deletable per entry (and with the child's profile, and with "delete everything"); names and vectors are never logged.

What it feeds (brain/perception.py Recognizer):
  person/parent  SFace face vector   -> label "<name>"   (an unknown face stays "a person")
  child          SFace face vector   -> label "the child"
  toy            MediaPipe embedder (or the OpenCV colour fallback) -> a toy is recognised without its ArUco tag
  item           same as toy         -> "the red cup" etc.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import config
from . import parent as P

log = logging.getLogger("teach")

KINDS = ("person", "child", "toy", "item")
ROLES = {"person": ("parent", "family"), "child": ("child",), "toy": ("toy",), "item": ("item",)}
MAX_VECS, MAX_ENTRIES, MAX_SHOTS = 12, 40, 10
FILE, AAD = "teach.enc", b"teach"

# Thing matching. The MediaPipe embedder and the colour fallback have different scales, so each has its own threshold
# (tunable at the venue: SENTIENT_THING_MATCH_MP / _HIST, see docs/vision.md for how they were chosen).
THING_MATCH = {"mp": float(os.environ.get("SENTIENT_THING_MATCH_MP", "0.80")),
               "hist": float(os.environ.get("SENTIENT_THING_MATCH_HIST", "0.90"))}
THING_MARGIN = 0.03        # the best entry must beat the runner-up by this much, or nothing is claimed


# ----------------------------------------------------------------------------------------------------------
# embedders
# ----------------------------------------------------------------------------------------------------------
def hist_embed(img) -> np.ndarray | None:
    """OpenCV-only appearance vector (no model needed): a Hellinger-style colour histogram, whole crop plus 2x2 cells, with
    the brightness stretched first so a dim toy camera and a bright one give similar vectors. Good for the toys' distinct
    plush colours; the MediaPipe embedder is used instead where it is installed."""
    if img is None or img.size == 0:
        return None
    small = cv2.resize(img, (48, 48), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2].astype(np.float32)
    lo, hi = np.percentile(v, (2, 98))
    hsv[..., 2] = np.clip((v - lo) * (255.0 / max(hi - lo, 24.0)), 0, 255).astype(np.uint8)

    def h(part, bins):
        x = cv2.calcHist([part], [0, 1, 2], None, bins, [0, 180, 0, 256, 0, 256]).flatten()
        return x / (x.sum() + 1e-9)
    cells = [h(hsv[r:r + 24, c:c + 24], [8, 2, 2]) for r in (0, 24) for c in (0, 24)]
    vec = np.sqrt(np.concatenate([h(hsv, [8, 4, 4])] + cells))
    return (vec / (np.linalg.norm(vec) + 1e-9)).astype(np.float32)


def _cos(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def regions(img, boxes=()) -> list[tuple[int, int, int, int]]:
    """Where a toy or item might be: the detector's boxes (largest two), the centre 60%, and the whole frame."""
    h, w = img.shape[:2]
    out = [tuple(int(v) for v in b) for b in sorted(boxes, key=lambda b: -b[2] * b[3])[:2] if b[2] > 12 and b[3] > 12]
    out.append((int(w * .2), int(h * .2), int(w * .6), int(h * .6)))
    out.append((0, 0, w, h))
    return out


# ----------------------------------------------------------------------------------------------------------
# the gallery the Recognizer matches against (an immutable snapshot)
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Gallery:
    people: list = field(default_factory=list)   # (name, role, [vec])   role: parent | family | child
    things: list = field(default_factory=list)   # (kind, name, embedder, [vec])   kind: toy | item

    def __bool__(self):
        return bool(self.people or self.things)

    def match_face(self, feat, threshold: float) -> tuple[str, str] | None:
        """(role, name) of the best enrolled face above the threshold."""
        best, score = None, 0.0
        for name, role, vecs in self.people:
            s = max(_cos(feat, v) for v in vecs)
            if s > score:
                best, score = (role, name), s
        return best if score >= threshold else None

    def match_things(self, candidates: dict, kinds=("toy", "item"), exclude=()) -> list[tuple[str, str, float, int]]:
        """candidates: embedder -> [vec per region]. Returns [(kind, name, score, region index)], each entry at most once.
        An entry counts only when it clears its embedder's threshold AND beats every other entry on that region by a margin."""
        found = {}
        for ri in range(max((len(v) for v in candidates.values()), default=0)):
            scored = []
            for kind, name, emb, vecs in self.things:
                cv = candidates.get(emb)
                if cv is None or ri >= len(cv) or cv[ri] is None or kind not in kinds or (kind, name) in exclude:
                    continue
                scored.append((max(_cos(cv[ri], v) for v in vecs), kind, name, emb))
            scored.sort(reverse=True)
            if not scored:
                continue
            s, kind, name, emb = scored[0]
            runner = next((x[0] for x in scored[1:] if (x[1], x[2]) != (kind, name) and x[3] == emb), 0.0)
            if s >= THING_MATCH[emb] and s - runner >= THING_MARGIN and s > found.get((kind, name), (0, 0))[0]:
                found[(kind, name)] = (s, ri)
        return [(k, n, s, ri) for (k, n), (s, ri) in found.items()]


EMPTY = Gallery()


# ----------------------------------------------------------------------------------------------------------
# the encrypted store
# ----------------------------------------------------------------------------------------------------------
class TeachStore:
    """Entries: {id, kind, name, role, child, embedder, vecs, consent, added}. Needs the Parent Board unlocked."""

    def __init__(self, parent: P.Parent):
        self.parent = parent
        self._cache: list | None = None
        self._cache_key = None
        self._gallery: Gallery | None = None
        self._lock = threading.RLock()

    # ---- persistence ----
    def _path(self):
        return os.path.join(self.parent.dir, FILE)

    def _entries(self) -> list:
        """The decrypted entries; [] while locked. Raises nothing for a missing file."""
        with self._lock:
            dek = self.parent._dek
            if dek is None:
                self._cache = self._gallery = self._cache_key = None
                return []
            if self._cache is None or self._cache_key is not dek:
                try:
                    with open(self._path(), "rb") as f:
                        self._cache = json.loads(self.parent._open(dek, f.read(), AAD))
                except OSError:
                    self._cache = []
                self._cache_key, self._gallery = dek, None
            return self._cache

    def _save(self):
        with self._lock:
            P._atomic_write(self._path(), self.parent._seal(self.parent._dek, json.dumps(self._cache).encode(), AAD))
            self._gallery = None

    def _need(self):
        if self.parent._dek is None:
            raise P.Locked()

    # ---- reading ----
    def list(self) -> list[dict]:
        """What the board shows: never the vectors."""
        self._need()
        return [{"id": e["id"], "kind": e["kind"], "name": e["name"], "role": e["role"], "photos": len(e["vecs"]),
                 "added": e["added"], "child": e.get("child")} for e in self._entries()]

    def gallery(self) -> Gallery:
        """Matching snapshot for the Recognizer; empty while the board is locked. Cheap: cached until something changes."""
        with self._lock:
            entries = self._entries()
            if self._gallery is None:
                g = Gallery()
                for e in entries:
                    vecs = [np.asarray(v, dtype=np.float32) for v in e["vecs"]]
                    if e["kind"] in ("person", "child"):
                        g.people.append((e["name"], e["role"], vecs))
                    else:
                        g.things.append((e["kind"], e["name"], e["embedder"], vecs))
                self._gallery = g
            return self._gallery

    # ---- writing ----
    def add(self, kind: str, name: str, vecs, embedder: str, consent: bool, role: str | None = None, child: str | None = None) -> dict:
        """Add vectors for a person / the child / a toy / an item (more photos of the same name are appended)."""
        with self._lock:
            self._need()
            if not consent:
                raise ValueError("A parent has to agree first (tick the consent box).")
            if kind not in KINDS:
                raise ValueError("Pick what to teach: a person, the child, a toy or an item.")
            if kind == "toy":
                if name not in config.TOYS:
                    raise ValueError("Pick one of the toys.")
                name = name.lower()
            else:
                name = P.safe_text(name, 40)
            if kind == "child":
                name = name or "child"
            if not name:
                raise ValueError("Give it a name first.")
            role = role if role in ROLES[kind] else ROLES[kind][0]
            vecs = [np.asarray(v, dtype=np.float32) for v in vecs if v is not None]
            if not vecs:
                raise ValueError("Nothing usable in those photos (a face or the item has to be clearly visible).")
            entries = self._entries()
            e = next((x for x in entries if x["kind"] == kind and x["name"].lower() == name.lower()
                      and (kind == "child" or x["embedder"] == embedder)), None)
            if e is None:
                if len(entries) >= MAX_ENTRIES:
                    raise ValueError("That is a lot of things to remember; delete one first.")
                e = {"id": secrets.token_hex(6), "kind": kind, "name": name, "role": role, "child": child, "embedder": embedder,
                     "vecs": [], "consent": dt.date.today().isoformat(), "added": dt.date.today().isoformat()}
                entries.append(e)
            e["vecs"] = (e["vecs"] + [[round(float(x), 5) for x in v] for v in vecs])[-MAX_VECS:]
            e["consent"] = dt.date.today().isoformat()
            self._save()
            return {"id": e["id"], "kind": kind, "name": e["name"], "role": e["role"], "photos": len(e["vecs"])}

    def delete(self, eid: str):
        with self._lock:
            self._need()
            entries = self._entries()
            keep = [e for e in entries if e["id"] != eid]
            if len(keep) == len(entries):
                raise KeyError(eid)
            self._cache[:] = keep
            self._save()

    def forget_child(self, cid: str):
        """The child's profile was deleted: so is their face."""
        with self._lock:
            if self.parent._dek is None:
                return
            entries = self._entries()
            keep = [e for e in entries if e.get("child") != cid]
            if len(keep) != len(entries):
                self._cache[:] = keep
                self._save()


# ----------------------------------------------------------------------------------------------------------
# enrolling from photos / a toy's camera (needs the Recognizer's models)
# ----------------------------------------------------------------------------------------------------------
def decode(data: bytes):
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    s = 640 / max(img.shape[:2])
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img


class Teacher:
    """Turns photos into vectors and hands them to the store. Photos never leave this function."""

    def __init__(self, store: TeachStore, rec, hub=None):
        self.store, self.rec, self.hub = store, rec, hub

    def face_vecs(self, imgs) -> list:
        out = []
        for img in imgs:
            faces = self.rec.faces(img)
            if faces:
                out.append(max(faces, key=lambda f: f[0][2] * f[0][3])[1])
        return out

    def thing_vecs(self, imgs) -> tuple[str, list]:
        """Embeddings of the centre of each photo (the parent holds the item up, centred) and of the detector's box."""
        embedder, out = None, []
        for img in imgs:
            boxes = [b for _, b, _ in self.rec.objects(img)]
            # the first region is the detector's box if there is one, then the centre; the whole frame is not enrolled
            for box in regions(img, boxes)[:-1]:
                name, vec = self.rec.thing_vec(img, box)
                if vec is not None:
                    embedder = embedder or name
                    if name == embedder:
                        out.append(vec)
        return embedder or self.rec.embedder_name, out

    def enroll(self, kind: str, name: str, imgs, consent: bool, role: str | None = None, child: str | None = None) -> dict:
        if not consent:
            raise ValueError("A parent has to agree first (tick the consent box).")
        imgs = [i for i in imgs if i is not None][:MAX_SHOTS]
        if kind in ("person", "child"):
            vecs, embedder = self.face_vecs(imgs), "sface"
        else:
            embedder, vecs = self.thing_vecs(imgs)
        res = self.store.add(kind, name, vecs, embedder, consent, role=role, child=child)
        res["frames"] = len(imgs)
        res["used"] = len(vecs)
        log.info("teach: %s enrolled from %d photo(s)", kind, len(imgs))   # no names, no vectors
        return res

    def capture(self, toy: str, shots: int = 6, gap: float = 0.4) -> list:
        """Frames from a toy's own camera. The camera is on only for this call, which a parent started."""
        if not self.hub:
            raise RuntimeError("The toys are not connected.")
        if toy not in config.TOYS or toy not in self.hub.online():
            raise ValueError("That toy is not online.")
        imgs = []
        for i in range(max(1, min(shots, MAX_SHOTS))):
            jpg = self.hub.capture(toy, force=True)
            if jpg:
                img = decode(jpg)
                if img is not None:
                    imgs.append(img)
            if i + 1 < shots:
                time.sleep(gap)
        if not imgs:
            raise ValueError("That toy's camera did not answer.")
        return imgs
