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

from . import config, teach

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
        self.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        self.obj = self.emb = None
        self.gallery = lambda: teach.EMPTY   # main wires the Parent Board's encrypted store here (brain/teach.py)
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
        log.info("enrolled (legacy file) people=%d pets=%d", len(self.people), len(self.pets))   # counts only, never names

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

    @property
    def embedder_name(self) -> str:
        return "mp" if self.emb else "hist"

    def thing_vec(self, img, box):
        """(embedder name, vector) for the region of a toy or household item: MediaPipe where installed, else a colour histogram."""
        x, y, w, h = box
        vec = self.embed(img, box)
        if vec is not None:
            return "mp", vec
        return "hist", teach.hist_embed(img[max(0, y):y + h, max(0, x):x + w])

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

    def _tags(self, img):
        """ArUco tags on the toys' chests. The toy cameras are small and often dim, so retry on a contrast-stretched copy."""
        corners, ids, _ = self.aruco.detectMarkers(img)
        if ids is not None and len(ids):
            return corners, ids
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        boosted = self.clahe.apply(gray)
        corners, ids, _ = self.aruco.detectMarkers(boosted)
        return (corners, ids) if ids is not None else ([], None)

    # ---------- full analysis ----------
    def analyze(self, img, own_toy: str | None = None) -> list[Thing]:
        things = []
        gal = self.gallery()
        for box, feat, sc in self.faces(img):
            name, _ = self.who(feat)
            hit = None if name else gal.match_face(feat, config.FACE_MATCH)   # the Parent Board's encrypted enrollments
            if hit:
                role, name = hit
                if role == "child":
                    name = "child"
            if name and name.strip().lower() in ("child", "the child"):
                things.append(Thing("child", "the child", box, sc))       # only a face enrolled as "child" is the child
            else:
                things.append(Thing("person", name or "a person", box, sc))   # anyone else: by name, or just "a person"
        corners, ids = self._tags(img)
        for c, i in zip(corners if ids is not None else [], ids.flatten() if ids is not None else []):
            toy = ARUCO_TO_TOY.get(int(i))
            if toy and toy != own_toy:
                x, y, w, h = cv2.boundingRect(c.astype(np.int32))
                # the tag is on the chest; widen the box to roughly the whole toy
                things.append(Thing("toy", config.TOYS[toy]["name"].upper(), (x - w, y - 2 * w, 3 * w, 4 * w)))
        objs = self.objects(img)
        things += self._taught(img, gal, own_toy, objs, {t.label for t in things if t.kind == "toy"})
        for cls, box, sc in objs:
            if cls in PET_CLASSES:
                pet = self.which_pet(cls, self.embed(img, box))
                things.append(Thing("pet", f"{cls} {pet}" if pet else f"a {cls}", box, sc))
            elif cls == "book":
                things.append(Thing("object", "a book", box, sc))
        return things

    def _taught(self, img, gal, own_toy, objs, tagged) -> list[Thing]:
        """Toys (recognised by how they look, no ArUco tag needed) and household items a parent taught the camera."""
        if not gal.things:
            return []
        regs = teach.regions(img, [b for _, b, _ in objs])
        cands: dict[str, list] = {}
        for emb in {t[2] for t in gal.things}:
            if emb == self.embedder_name:
                cands[emb] = [self.thing_vec(img, r)[1] for r in regs]
        skip = {("toy", k) for k in config.TOYS if k == own_toy or config.TOYS[k]["name"].upper() in tagged}
        out = []
        for kind, name, score, ri in gal.match_things(cands, exclude=skip):
            if kind == "toy":
                out.append(Thing("toy", config.TOYS[name]["name"].upper(), regs[ri], score))
            else:
                out.append(Thing("object", name, regs[ri], score))
        return out


def _salience(t: Thing, w, h):
    x, y, bw, bh = t.box
    cx, cy = (x + bw / 2) / w - 0.5, (y + bh / 2) / h - 0.5
    return (bw * bh) / (w * h) * (1.2 - min(1.0, (cx * cx + cy * cy) ** 0.5 * 1.6)) + (0.05 if t.kind != "object" else 0)


class Perceiver:
    """Camera policy (brain/camera.py): cameras are OFF. snap(toy) takes ONE picture on demand (the child asked what the toy
    sees) and close(toy) drops it again. Only with SENTIENT_CAMERA_CONTINUOUS=1 does start() poll every toy's camera, keep the
    latest View and fire on_seen(toy, Thing) for new familiar faces/pets (the old behaviour)."""

    def __init__(self, hub, rec: Recognizer, on_seen=None):
        self.hub, self.rec = hub, rec
        self.on_seen = on_seen or (lambda toy, thing: None)
        self.views = {t: View(t) for t in config.TOY_ORDER}
        self.hold = lambda: False   # main wires this to 'the director is mid-turn'
        self._last_greet: dict[str, float] = {}

    def start(self):
        if not config.CAPTURE_CONTINUOUS:
            log.info("cameras are off: a toy looks only when the child asks (SENTIENT_CAMERA_CONTINUOUS=1 turns continuous capture back on)")
            return
        for toy in config.TOY_ORDER:
            threading.Thread(target=self._loop, args=(toy,), daemon=True, name=f"eyes-{toy}").start()

    def snap(self, toy) -> View | None:
        """On demand: one frame from `toy`'s camera (allowed mid-turn), analysed and kept in RAM as that toy's View. No greeting
        fires. The caller ends it with close(toy) once it has the frame."""
        jpg = self.hub.capture(toy, force=True)
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR) if jpg else None
        if img is None:
            return None
        try:
            self._update(toy, img, jpg, greet=False)
        except Exception:  # noqa: BLE001
            log.exception("perception failed for %s", toy)
            self.views[toy] = View(toy, time.time(), True, [], None, jpg)
        return self.views[toy]

    def close(self, toy):
        """Camera off again: forget the frame (the dashboard shows 'camera off'). Continuous mode keeps its rolling view."""
        if not config.CAPTURE_CONTINUOUS:
            self.views[toy] = View(toy)

    def scene_text(self) -> str:
        if not config.CAPTURE_CONTINUOUS and not any(v.eyes for v in self.views.values()):
            return "All cameras are off; a toy looks only when the child asks."
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

    def _update(self, toy, img, jpg, greet=True):
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
        for t in things if greet else ():
            if t.kind in ("person", "pet") and now - self._last_greet.get(t.label, 0) > config.GREET_COOLDOWN_S:
                self._last_greet[t.label] = now
                self.on_seen(toy, t)
