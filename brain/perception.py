"""What each toy is looking at: child, family, pets, other toys, books.

Faces: OpenCV YuNet + SFace (all platforms). Toys: ArUco tags.
Pets/books: MediaPipe EfficientDet-Lite0 + Image Embedder on LiteRT
(Pi/Jetson; skipped where mediapipe isn't installed, e.g. Intel Mac).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import config

log = logging.getLogger("perception")
ARUCO_TO_TOY = {t["aruco"]: k for k, t in config.TOYS.items()}
PET_CLASSES = {"dog", "cat"}
OBJ_CLASSES = ["dog", "cat", "book", "teddy bear"]


@dataclass
class Thing:
    kind: str          # child | person | pet | toy | object
    label: str         # "the child", "Grandma", "dog Biscuit", "SAGE", "a book"
    box: tuple         # x, y, w, h
    score: float = 1.0


@dataclass
class View:
    toy: str
    ts: float = 0.0
    eyes: bool = False
    things: list = field(default_factory=list)
    looking_at: Thing | None = None
    jpeg: bytes | None = None        # latest raw frame (for vision turns)
    annotated: bytes | None = None   # for the dashboard

    def describe(self) -> str:
        name = config.TOYS[self.toy]["name"].upper()
        if not self.eyes or time.time() - self.ts > 8:
            return f"{name}'s eyes are closed."
        if not self.things:
            return f"{name} sees nothing in particular."
        others = [t.label for t in self.things if t is not self.looking_at]
        s = f"{name} is looking at {self.looking_at.label}"
        return s + (f"; also sees {', '.join(others)}." if others else ".")


def _cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


class Recognizer:
    """Shared models + enrolled identities (thread-safe for our 1–3 callers via a lock)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.face_det = cv2.FaceDetectorYN.create(str(config.YUNET), "", (320, 240), 0.7, 0.3, 20)
        self.face_rec = cv2.FaceRecognizerSF.create(str(config.SFACE), "")
        self.aruco = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
                                             cv2.aruco.DetectorParameters())
        self.obj = self.emb = None
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
            self._mp = mp
            self.obj = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(config.OBJ_DET)),
                score_threshold=0.35, max_results=5, category_allowlist=OBJ_CLASSES))
            self.emb = vision.ImageEmbedder.create_from_options(vision.ImageEmbedderOptions(
                base_options=BaseOptions(model_asset_path=str(config.EMBEDDER)), l2_normalize=True))
            log.info("MediaPipe (LiteRT) object detector + embedder ready")
        except Exception as e:  # noqa: BLE001 — any failure just disables pets
            log.warning("MediaPipe unavailable (%s): pets/books disabled, faces+tags still work", e)
        self.load_db()

    # ---------- enrolled identities ----------
    def load_db(self):
        self.people: dict[str, list[np.ndarray]] = {}
        self.pets: dict[str, tuple[str, list[np.ndarray]]] = {}
        if config.ENROLL_DB.exists():
            db = np.load(config.ENROLL_DB, allow_pickle=True)
            self.people = db["people"].item()
            self.pets = db["pets"].item()
        log.info("enrolled people=%s pets=%s", list(self.people), list(self.pets))

    def save_db(self):
        np.savez(config.ENROLL_DB, people=np.array(self.people, dtype=object), pets=np.array(self.pets, dtype=object))

    # ---------- primitives ----------
    def faces(self, img):
        with self.lock:
            self.face_det.setInputSize((img.shape[1], img.shape[0]))
            _, faces = self.face_det.detect(img)
            out = []
            for f in faces if faces is not None else []:
                feat = self.face_rec.feature(self.face_rec.alignCrop(img, f)).flatten()
                out.append((tuple(int(v) for v in f[:4]), feat, float(f[-1])))
        return out

    def objects(self, img):
        if not self.obj:
            return []
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        with self.lock:
            res = self.obj.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        out = []
        for d in res.detections:
            b = d.bounding_box
            out.append((d.categories[0].category_name, (b.origin_x, b.origin_y, b.width, b.height),
                        d.categories[0].score))
        return out

    def embed(self, img, box):
        if not self.emb:
            return None
        x, y, w, h = box
        crop = img[max(0, y):y + h, max(0, x):x + w]
        if crop.size == 0:
            return None
        rgb = np.ascontiguousarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        with self.lock:
            r = self.emb.embed(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        return np.array(r.embeddings[0].embedding, dtype=np.float32)

    def who(self, feat) -> tuple[str | None, float]:
        best, score = None, 0.0
        for name, feats in self.people.items():
            s = max(_cos(feat, f) for f in feats)
            if s > score:
                best, score = name, s
        return (best, score) if score >= config.FACE_MATCH else (None, score)

    def which_pet(self, species, vec) -> str | None:
        cands = {n: fs for n, (sp, fs) in self.pets.items() if sp == species}
        if not cands:
            return None
        if vec is None or len(cands) == 1:
            return next(iter(cands))
        name, s = max(((n, max(_cos(vec, f) for f in fs)) for n, fs in cands.items()), key=lambda x: x[1])
        return name if s >= config.PET_MATCH else None

    # ---------- full analysis ----------
    def analyze(self, img, own_toy: str | None = None) -> list[Thing]:
        things = []
        for box, feat, sc in self.faces(img):
            name, _ = self.who(feat)
            things.append(Thing("person", name, box, sc) if name else Thing("child", "the child", box, sc))
        corners, ids, _ = self.aruco.detectMarkers(img)
        for c, i in zip(corners if ids is not None else [], ids.flatten() if ids is not None else []):
            toy = ARUCO_TO_TOY.get(int(i))
            if toy and toy != own_toy:
                x, y, w, h = cv2.boundingRect(c.astype(np.int32))
                # the tag is on the chest; widen the box to roughly the whole toy
                things.append(Thing("toy", config.TOYS[toy]["name"].upper(), (x - w, y - 2 * w, 3 * w, 4 * w)))
        for cls, box, sc in self.objects(img):
            if cls in PET_CLASSES:
                pet = self.which_pet(cls, self.embed(img, box))
                things.append(Thing("pet", f"{cls} {pet}" if pet else f"a {cls}", box, sc))
            elif cls == "book":
                things.append(Thing("object", "a book", box, sc))
        return things


def _salience(t: Thing, w, h):
    x, y, bw, bh = t.box
    cx, cy = (x + bw / 2) / w - 0.5, (y + bh / 2) / h - 0.5
    return (bw * bh) / (w * h) * (1.2 - min(1.0, (cx * cx + cy * cy) ** 0.5 * 1.6)) + (0.05 if t.kind != "object" else 0)


class Perceiver:
    """Polls each toy's camera, keeps the latest View, fires on_seen(toy, Thing) for new familiar faces/pets."""

    def __init__(self, hub, rec: Recognizer, on_seen=None):
        self.hub, self.rec = hub, rec
        self.on_seen = on_seen or (lambda toy, thing: None)
        self.views = {t: View(t) for t in config.TOY_ORDER}
        self.hold = lambda: False   # main wires this to 'the director is mid-turn'
        self._last_greet: dict[str, float] = {}

    def start(self):
        for toy in config.TOY_ORDER:
            threading.Thread(target=self._loop, args=(toy,), daemon=True, name=f"eyes-{toy}").start()

    def scene_text(self) -> str:
        return " ".join(self.views[t].describe() for t in self.hub.online()) or "No toys can see right now."

    def _loop(self, toy):
        period = 1.0 / config.CAPTURE_FPS
        while True:
            t0 = time.time()
            # All cameras pause for the whole turn (Gemma thinking + toys talking): on a Pi the
            # face/pet models would otherwise compete with LiteRT for the CPU. The turn uses the
            # last views, which are at most one capture period old.
            busy = self.hub.talking is not None or self.hold()
            jpg = None if busy else self.hub.capture(toy)
            if jpg:
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    try:
                        self._update(toy, img, jpg)
                    except Exception:  # noqa: BLE001
                        log.exception("perception failed for %s", toy)
            time.sleep(max(0.05, period - (time.time() - t0)))

    def _update(self, toy, img, jpg):
        h, w = img.shape[:2]
        things = self.rec.analyze(img, own_toy=toy)
        things.sort(key=lambda t: _salience(t, w, h), reverse=True)
        v = View(toy, time.time(), True, things, things[0] if things else None, jpg)
        ann = img.copy()
        colors = {"child": (0, 200, 255), "person": (0, 255, 0), "pet": (255, 120, 0), "toy": (255, 0, 255),
                  "object": (200, 200, 200)}
        for t in things:
            x, y, bw, bh = t.box
            cv2.rectangle(ann, (x, y), (x + bw, y + bh), colors[t.kind], 3 if t is v.looking_at else 1)
            cv2.putText(ann, t.label, (x, max(12, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colors[t.kind], 1)
        v.annotated = cv2.imencode(".jpg", ann)[1].tobytes()
        self.views[toy] = v
        now = time.time()
        for t in things:
            if t.kind in ("person", "pet") and now - self._last_greet.get(t.label, 0) > config.GREET_COOLDOWN_S:
                self._last_greet[t.label] = now
                self.on_seen(toy, t)
