"""Sound effects (CC0, from tools/fetch_sfx.py) that toys mix into what they say.

A line can carry tags: "{knock} Who could that be?" plays the knock, then the speech.
A spoken "Rawr!" becomes Dyno's growl sound, since TTS makes it sound bad.
"""
from __future__ import annotations

import json
import logging
import re
import wave

import numpy as np

from . import config

log = logging.getLogger("sfx")
TAG = re.compile(r"\{([a-z_]+)\}")
RAWR = re.compile(r"\b(?:r+a+w+r+|g+r+r+)\b[!.,]*", re.I)   # "Rawr!", "Grrr" -> growl sound
ROAR = re.compile(r"\bROAR\b[!.,]*")                       # shouted ROAR -> big roar
GAP = np.zeros(int(0.08 * config.SAMPLE_RATE), "<i2").tobytes()


class Sounds:
    def __init__(self):
        self.index, self.pcm = {}, {}
        try:
            self.index = json.loads((config.SFX_DIR / "index.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            log.warning("no sound effects in %s (run tools/fetch_sfx.py)", config.SFX_DIR)
            return
        for name in list(self.index):
            try:
                with wave.open(str(config.SFX_DIR / f"{name}.wav")) as w:
                    if w.getframerate() != config.SAMPLE_RATE or w.getnchannels() != 1:
                        raise ValueError("expected 16 kHz mono")
                    self.pcm[name] = w.readframes(w.getnframes())
            except (OSError, ValueError, wave.Error) as e:
                log.warning("sound %s unusable: %s", name, e)
                self.index.pop(name)
        log.info("%d sound effects loaded", len(self.pcm))

    def names(self, toy: str | None = None) -> list[str]:
        """Story sounds plus the toy's own creature sounds (all sounds if toy is None)."""
        return sorted(n for n, v in self.index.items() if toy is None or v.get("toy") in (None, toy))

    def prompt_list(self) -> str:
        story = ", ".join(n for n, v in self.index.items() if not v.get("toy") and v.get("set") != "halloween")
        spooky = ", ".join(n for n, v in self.index.items() if v.get("set") == "halloween")
        own = "; ".join(f"{t.upper()}: {', '.join(n for n, v in self.index.items() if v.get('toy') == t)}"
                        for t in sorted({v['toy'] for v in self.index.values() if v.get('toy')}))
        return (f"story sounds: {story}. Halloween sounds (only for spooky stories, keep it fun): {spooky}. "
                f"Character sounds — {own}.")

    def affects(self, text: str) -> bool:
        return bool(self.pcm) and bool(TAG.search(text) or RAWR.search(text) or ROAR.search(text))

    def segments(self, text: str) -> list[tuple[str, str]]:
        """[("sfx", name) | ("say", text)] in order; unknown tags are dropped."""
        text = ROAR.sub(" {dino_roar} ", text)
        text = RAWR.sub(" {dino_growl} ", text)
        out, pos = [], 0
        for m in TAG.finditer(text):
            before = text[pos:m.start()].strip(" ,")
            if before:
                out.append(("say", before))
            if m.group(1) in self.pcm:
                out.append(("sfx", m.group(1)))
            pos = m.end()
        rest = text[pos:].strip(" ,")
        if rest:
            out.append(("say", rest))
        return out
