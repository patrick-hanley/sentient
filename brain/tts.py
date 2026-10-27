"""Per-toy voices (Kokoro or Piper), rendered to 16 kHz mono int16 bytes for the Atoms."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.request

import numpy as np

from . import config

log = logging.getLogger("tts")
KITTEN_URL = "http://127.0.0.1:8099/tts"   # tools/kitten_server.py, a Python 3.12 sidecar
KITTEN_VOICES = ["Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"]


def _apply_gain(pcm: bytes, gain: float) -> bytes:
    """Volume: scale, then limit the peak so loud settings get louder without crackling."""
    if abs(gain - 1.0) < 1e-3 or not pcm:
        return pcm
    x = np.frombuffer(pcm, "<i2").astype(np.float32) * gain
    peak = float(np.abs(x).max())
    if peak > 30000:
        x *= 30000 / peak
    return x.astype("<i2").tobytes()


def _resample(x: np.ndarray, src: float, dst: float) -> np.ndarray:
    if abs(src - dst) < 1:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


class Voices:
    def __init__(self):
        from piper import PiperVoice  # imported here so --help works without piper
        self._voices = {}
        self._lock = threading.Lock()
        for name in {t["voice"] for t in config.TOYS.values()}:
            path = config.OFFLINE / "piper" / f"{name}.onnx"
            self._voices[name] = PiperVoice.load(str(path))
            log.info("voice loaded: %s", name)
        self._cache: dict[tuple[str, str], bytes] = {}
        self.last: dict[str, str] = {}     # toy -> "3.6 s of speech in 3.9 s" (dashboard)
        self._live = 0                     # live renders in progress: background prerender yields to them
        self._last_live = 0.0
        self.busy = lambda: False          # main wires this to "the director is mid-turn"
        self._disk = config.DATA / "tts-cache"
        self._disk.mkdir(parents=True, exist_ok=True)
        from .sfx import Sounds
        self.sounds = Sounds()
        self._kokoro, self._kokoro_model = None, None
        if config.USE_KOKORO and any(t.get("kokoro") for t in config.TOYS.values()):
            try:
                import onnxruntime as rt
                from kokoro_onnx import Kokoro
                model = config.KOKORO_DIR / config.KOKORO_MODEL
                if not model.exists():
                    model = config.KOKORO_DIR / "kokoro-v1.0.onnx"
                opts = rt.SessionOptions()
                opts.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL  # ~25% faster int8 on the Pi
                session = rt.InferenceSession(str(model), sess_options=opts, providers=["CPUExecutionProvider"])
                self._kokoro = Kokoro.from_session(session, str(config.KOKORO_DIR / "voices-v1.0.bin"))
                self._kokoro_model = model.name
                log.info("Kokoro loaded (%s): %s", model.name,
                         {k: t["kokoro"] for k, t in config.TOYS.items() if t.get("kokoro")})
            except Exception as e:  # noqa: BLE001 — missing package/files: Piper for everyone
                log.warning("Kokoro unavailable (%s) — using Piper voices", e)

    def render(self, toy: str, text: str, *, persist: bool = False) -> bytes:
        key = (toy, text)
        if key in self._cache:
            return self._cache[key]
        t = config.TOYS[toy]
        kokoro = self._kokoro is not None and bool(t.get("kokoro"))
        # disk cache for fixed lines (fillers, canned scene): keyed by engine + voice settings + text
        path = self._disk / (self._spec_hash(toy, text) + ".pcm")
        if persist and path.exists():
            pcm = path.read_bytes()
        else:
            if not persist:
                self._live += 1
            try:
                start = time.time()
                pcm = self._render_with_sfx(t, text, kokoro)
                pcm = _apply_gain(pcm, (t.get("gain") or 1.0))
                self.last[toy] = f"{len(pcm) / 2 / config.SAMPLE_RATE:.1f} s of speech in {time.time() - start:.1f} s"
            finally:
                if not persist:
                    self._live -= 1
                    self._last_live = time.time()
            if persist:
                path.write_bytes(pcm)
        if len(self._cache) < 500:
            self._cache[key] = pcm
        return pcm

    def _render_with_sfx(self, t: dict, text: str, kokoro: bool) -> bytes:
        """Speech with sound effects mixed in: '{knock} Who is it?' -> knock, short gap, speech."""
        if t.get("kitten") and self._kitten_up():
            speak = lambda x: self._render_kitten(t, x)
        else:
            speak = (lambda x: self._render_kokoro(t, x)) if kokoro else (lambda x: self._render_piper(t, x))
        if not self.sounds.affects(text):
            return speak(text)
        parts = []
        for kind, value in self.sounds.segments(text):
            if kind == "sfx":
                gain = 1.0 / max((t.get("gain") or 1.0), 1e-3)   # sounds keep their level; volume applies after
                parts.append(_apply_gain(self.sounds.pcm[value], gain))
            elif any(ch.isalnum() for ch in value):
                parts.append(speak(value))
        from .sfx import GAP
        return GAP.join(p for p in parts if p)

    def _spec_hash(self, toy: str, text: str) -> str:
        t = config.TOYS[toy]
        kokoro = self._kokoro is not None and bool(t.get("kokoro"))
        spec = {"k": kokoro and self._kokoro_model, "t": text,
                **{f: t.get(f) for f in ("kokoro", "kspeed", "kpitch", "voice", "speaker", "length", "pitch")}}
        if t.get("kitten"):   # only part of the key when used, so existing clips stay valid
            spec["kt"] = t["kitten"]
        if (t.get("gain") or 1.0) != 1.0:   # only part of the key when changed, so existing clips stay valid
            spec["g"] = t["gain"]
        if self.sounds.affects(text):    # lines with sound effects (and "Rawr!") render differently now
            spec["sfx"] = 1
        return hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()

    def clip_id(self, toy: str, text: str) -> str:
        """Name of this line as a clip stored on the Atom (changes when the voice or text changes)."""
        return "c" + self._spec_hash(toy, text)[:12]

    # ---------- dashboard voice editing ----------
    def kokoro_voices(self) -> list[str]:
        return sorted(self._kokoro.get_voices()) if self._kokoro is not None else []

    def piper_voices(self) -> list[str]:
        return sorted(p.stem for p in (config.OFFLINE / "piper").glob("*.onnx"))

    def preview(self, toy: str, engine: str, voice: str, speed: float, pitch: float, volume: float,
                speaker=None, text: str = "Hi! This is how I sound now. Do you like my voice?") -> bytes:
        """Render with unsaved dashboard values (the Test button) — nothing is changed or cached."""
        saved = dict(config.TOYS[toy])
        try:
            self.apply(toy, engine, voice, speed, pitch, volume, speaker, persist=False)
            t = config.TOYS[toy]
            kokoro = self._kokoro is not None and bool(t.get("kokoro"))
            with_sfx = self._render_with_sfx(t, text, kokoro)
            return _apply_gain(with_sfx, t.get("gain") or 1.0)
        finally:
            config.TOYS[toy].clear()
            config.TOYS[toy].update(saved)

    def settings(self, toy: str) -> dict:
        """Editable voice settings in one engine-neutral shape."""
        t = config.TOYS[toy]
        if t.get("kitten"):
            return {"engine": "kitten", "voice": t["kitten"], "speed": t.get("kspeed", 1.0),
                    "pitch": t.get("kpitch", 1.0), "volume": (t.get("gain") or 1.0), "speaker": None}
        if self._kokoro is not None and t.get("kokoro"):
            return {"engine": "kokoro", "voice": t["kokoro"], "speed": t.get("kspeed", 1.0),
                    "pitch": t.get("kpitch", 1.0), "volume": (t.get("gain") or 1.0), "speaker": None}
        return {"engine": "piper", "voice": t["voice"], "speed": round(1 / t["length"], 2),
                "pitch": t["pitch"], "volume": (t.get("gain") or 1.0), "speaker": t.get("speaker")}

    def apply(self, toy: str, engine: str, voice: str, speed: float, pitch: float, volume: float,
              speaker=None, persist: bool = True) -> dict:
        """Change a toy's voice live (validated), persist it, and drop its cached audio."""
        clamp = lambda x, lo, hi: max(lo, min(hi, float(x)))
        speed, pitch, volume = clamp(speed, 0.6, 1.6), clamp(pitch, 0.7, 1.6), clamp(volume, 0.2, 2.5)
        t = config.TOYS[toy]
        if engine == "kitten":
            if voice not in KITTEN_VOICES:
                raise ValueError(f"unknown Kitten voice {voice!r}")
            t.update(kitten=voice, kspeed=speed, kpitch=pitch)
        elif engine == "kokoro":
            if voice not in self.kokoro_voices():
                raise ValueError(f"unknown Kokoro voice {voice!r}")
            t.update(kitten=None, kokoro=voice, kspeed=speed, kpitch=pitch)
        elif engine == "piper":
            if voice not in self.piper_voices():
                raise ValueError(f"unknown Piper voice {voice!r}")
            t.update(kitten=None, kokoro=None, voice=voice, length=round(1 / speed, 3), pitch=pitch,
                     speaker=int(speaker) if speaker not in (None, "", "null") else None)
        else:
            raise ValueError("engine must be kokoro, piper or kitten")
        t["gain"] = volume
        if not persist:
            return self.settings(toy)
        config.save_voice_settings()
        self._cache = {k: v for k, v in self._cache.items() if k[0] != toy}
        self.last.pop(toy, None)
        return self.settings(toy)

    def describe(self, toy: str) -> dict:
        """Dashboard summary of a toy's voice."""
        t = config.TOYS[toy]
        if t.get("kitten"):
            return {"engine": "Kitten TTS nano", "label": t["kitten"], "quant": "int8", "id": t["kitten"],
                    "speed": t.get("kspeed", 1.0), "pitch": t.get("kpitch", 1.0), "model": "kitten-tts-nano-0.8-int8",
                    "last": self.last.get(toy, "")}
        if self._kokoro is not None and t.get("kokoro"):
            v = t["kokoro"]   # e.g. af_heart: a/b = American/British, f/m = female/male
            accent = {"a": "American", "b": "British"}.get(v[0], v[0])
            gender = {"f": "female", "m": "male"}.get(v[1], "")
            m = (self._kokoro_model or "").lower()
            quant = next((q for q in ("int8", "uint8", "q4", "q8f16", "fp16", "int4", "int2") if q in m), "fp32")
            return {"engine": "Kokoro-82M", "label": f"{v.split('_', 1)[1].title()} · {accent} {gender}".strip(), "quant": quant,
                    "id": v, "speed": t.get("kspeed", 1.0), "pitch": t.get("kpitch", 1.0),
                    "model": self._kokoro_model, "last": self.last.get(toy, "")}
        name = t["voice"]   # e.g. en_GB-alba-medium
        accent = {"en_GB": "British", "en_US": "American"}.get(name.split("-")[0], name.split("-")[0])
        label = f"{name.split('-')[1].replace('_', ' ').title()} · {accent}" + (f" #{t['speaker']}" if t.get("speaker") is not None else "")
        return {"engine": "Piper", "label": label, "id": name, "quant": "fp32", "speed": round(1 / t["length"], 2),
                "pitch": t["pitch"], "model": name, "last": self.last.get(toy, "")}

    def _render_kokoro(self, t: dict, text: str) -> bytes:
        voice, pitch = t["kokoro"], t.get("kpitch", 1.0)
        start = time.time()
        with self._lock:
            # same pitch trick as Piper: speak slower by `pitch`, then play `pitch`x faster
            audio, sr = self._kokoro.create(text, voice=voice, speed=t.get("kspeed", 1.0) / pitch,
                                            lang="en-gb" if voice.startswith("b") else "en-us")
        audio = _resample(np.asarray(audio, np.float32) * 32767, sr * pitch, config.SAMPLE_RATE)
        log.info("kokoro %s: %.1fs speech in %.1fs", voice, len(audio) / config.SAMPLE_RATE, time.time() - start)
        return np.clip(audio, -32768, 32767).astype("<i2").tobytes()

    _kitten_down_until = 0.0

    def _kitten_up(self) -> bool:
        """The sidecar answers; after a failure fall back to Kokoro/Piper for 30 s instead of retrying every line."""
        return time.time() >= self._kitten_down_until

    def _render_kitten(self, t: dict, text: str) -> bytes:
        voice, pitch = t["kitten"], t.get("kpitch", 1.0)
        start = time.time()
        speed = t.get("kspeed", 1.0) / pitch
        req = urllib.request.Request(f"{KITTEN_URL}?voice={voice}&speed={speed:.3f}", data=text.encode(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
        except OSError as e:
            Voices._kitten_down_until = time.time() + 30
            log.warning("Kitten sidecar unavailable (%s) — using Kokoro/Piper for 30 s", e)
            kokoro = self._kokoro is not None and bool(t.get("kokoro"))
            return self._render_kokoro(t, text) if kokoro else self._render_piper(t, text)
        audio = _resample(np.frombuffer(raw, "<i2").astype(np.float32), 24000 * pitch, config.SAMPLE_RATE)
        log.info("kitten %s: %.1fs speech in %.1fs", voice, len(audio) / config.SAMPLE_RATE, time.time() - start)
        return np.clip(audio, -32768, 32767).astype("<i2").tobytes()

    def _render_piper(self, t: dict, text: str) -> bytes:
        from piper import PiperVoice, SynthesisConfig
        if t["voice"] not in self._voices:   # chosen on the dashboard: load on first use
            self._voices[t["voice"]] = PiperVoice.load(str(config.OFFLINE / "piper" / f"{t['voice']}.onnx"))
        voice = self._voices[t["voice"]]
        syn = SynthesisConfig(speaker_id=t["speaker"], length_scale=t["length"] * t["pitch"])
        with self._lock:  # onnxruntime sessions are not re-entrant-safe across threads here
            chunks = list(voice.synthesize(text, syn_config=syn))
        if not chunks:
            return b""
        sr = chunks[0].sample_rate
        audio = np.concatenate([c.audio_int16_array for c in chunks]).astype(np.float32)
        # pitch trick: synthesized slower by `pitch`, then played back `pitch`x faster.
        audio = _resample(audio, sr * t["pitch"], config.SAMPLE_RATE)
        return np.clip(audio, -32768, 32767).astype("<i2").tobytes()

    def prerender(self, lines: list[tuple[str, str]], *, polite: bool = False) -> None:
        """Render fixed lines once (cached on disk). `polite` waits for live speech and turns."""
        for toy, text in lines:
            while polite and (self._live or self.busy() or time.time() - self._last_live < 3):
                time.sleep(0.5)
            self.render(toy, text, persist=True)
