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
SLEEP_ONLY = ("snore_",)

# Non-speech vocalizations are never spelled out for the voice to read ("zzz", "hee hee", "yawn..."): they become the recorded
# sounds. A bracketed word ("[snoring]", "[laughs]") is the same request. Brackets we do not know are dropped, not spoken.
SNORE_WORDS = {"shh", "shhh", "shhhh", "hush", "snore", "snores", "snoring", "snoozing", "sleeping", "asleep", "zzz"}
YAWN_WORDS = {"yawn", "yawns", "yawning"}
LAUGH_WORDS = {"laugh", "laughs", "laughing", "laughter", "giggle", "giggles", "giggling", "chuckle", "chuckles", "chuckling"}
SIGH_WORDS = {"sigh", "sighs", "sighing"}
SILENT_WORDS = {"cough", "coughs", "coughing", "sneeze", "sneezes", "sneezing", "breathing", "heavy breathing", "burp", "burps",
                "clears throat", "clearing throat", "inaudible", "blank audio", "blank_audio", "silence", "noise", "music",
                "background noise", "sniff", "sniffs", "sniffling", "gasp", "gasps", "groan", "groans"}
VOCAL_TAG = {**{w: "snore" for w in SNORE_WORDS}, **{w: "yawn" for w in YAWN_WORDS},
             **{w: "giggle" for w in LAUGH_WORDS}, **{w: "sigh" for w in SIGH_WORDS}}
BRACKET = re.compile(r"\[\s*([A-Za-z][A-Za-z _-]{1,24}?)\s*\]|\*\s*([A-Za-z][A-Za-z ]{1,20}?)\s*\*|\(\s*([A-Za-z][A-Za-z ]{1,20}?)\s*\)")
SHH = re.compile(r"\b[Ss]h{2,}\b(?:[\s,-]+[Ss]h{2,}\b)*[!.\u2026,]*")   # "Shhh", "shh, shh": a hush is the recorded sound, never spelled
ZZZ = re.compile(r"\b[Zz]{2,}\b[.\u2026]*")
LAUGH = re.compile(r"\b(?:hee|ha|heh|tee)(?:[\s,-]+(?:hee|ha|heh|tee))+\b[!.\u2026]*|\b(?:ha){2,}\b[!.]*|\b(?:he){2,}\b[!.]*|\bteehee\b[!.]*", re.I)
YAWN = re.compile(r"\b[Yy]a+w+n+s?(?=\s*(?:\.{2,}|\u2026|[!,]))[\s.\u2026!,]*")
SIGH = re.compile(r"\b[Ss]ighs?(?=\s*(?:\.{2,}|\u2026|[!,]))[\s.\u2026!,]*")
HONK = re.compile(r"\bhonk\b[!.,\u2026]*", re.I)
VOCAL_PATTERNS = (SHH, ZZZ, LAUGH, YAWN, SIGH, HONK)
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
        shown = {n: v for n, v in self.index.items() if not n.startswith(SLEEP_ONLY)}   # snores are for sleeping toys, not chatter
        story = ", ".join(n for n, v in shown.items() if not v.get("toy") and v.get("set") != "halloween")
        spooky = ", ".join(n for n, v in shown.items() if v.get("set") == "halloween")
        own = "; ".join(f"{t.upper()}: {', '.join(n for n, v in shown.items() if v.get('toy') == t)}"
                        for t in sorted({v['toy'] for v in shown.values() if v.get('toy')}))
        return (f"story sounds: {story}. Halloween sounds (only for spooky stories, keep it fun): {spooky}. "
                f"Character sounds — {own}.")

    def affects(self, text: str) -> bool:
        return bool(self.pcm) and bool(TAG.search(text) or RAWR.search(text) or ROAR.search(text)
                                       or any(p.search(text) for p in VOCAL_PATTERNS) or self._brackets(text))

    @staticmethod
    def _bracket_word(m) -> str:
        return next(g for g in m.groups() if g).strip().lower().replace("_", " ")

    def _brackets(self, text: str) -> bool:
        """True when the text has an annotation we handle: a known vocalization, or a short bracketed/starred word to drop."""
        for m in BRACKET.finditer(text):
            w = self._bracket_word(m)
            if w in VOCAL_TAG or w in SILENT_WORDS:
                return True
            if m.group(1) is not None and len(w.split()) <= 3:   # "[something]": a label, never speech (parentheses and stars may be speech)
                return True
        return False

    def _snore_for(self, toy: str | None) -> str | None:
        own = [n for n, v in self.index.items() if n.startswith(SLEEP_ONLY) and v.get("toy") == toy and n in self.pcm]
        anyone = [n for n in self.pcm if n.startswith(SLEEP_ONLY)]
        return (own or anyone or [None])[0]

    def _tagged(self, text: str) -> str:
        """Spoken vocalizations and bracketed words -> {sound} tags; unknown bracketed labels are removed."""
        def bracket(m):
            w = self._bracket_word(m)
            if w in VOCAL_TAG:
                return " {%s} " % VOCAL_TAG[w]
            if w in SILENT_WORDS or (m.group(1) is not None and len(w.split()) <= 3):
                return " "
            return m.group(0)
        text = BRACKET.sub(bracket, text)
        text = SHH.sub(" {snore} ", text)
        text = ZZZ.sub(" {snore} ", text)
        text = LAUGH.sub(" {giggle} ", text)
        text = YAWN.sub(" {yawn} ", text)
        text = SIGH.sub(" {sigh} ", text)
        return HONK.sub(" {penguin_honk} ", text)

    def display(self, text: str) -> str:
        """The text with every recorded sound shown as a {tag}, for the dashboard (not for speech)."""
        return self._tagged(RAWR.sub(" {dino_growl} ", ROAR.sub(" {dino_roar} ", text))).replace("  ", " ").strip()

    def segments(self, text: str, toy: str | None = None) -> list[tuple[str, str]]:
        """[("sfx", name) | ("say", text)] in order; unknown tags are dropped."""
        text = ROAR.sub(" {dino_roar} ", text)
        text = RAWR.sub(" {dino_growl} ", text)
        text = self._tagged(text)
        out, pos = [], 0
        for m in TAG.finditer(text):
            before = text[pos:m.start()].strip(" ,")
            if before:
                out.append(("say", before))
            name = self._snore_for(toy) if m.group(1) == "snore" else m.group(1)
            if name in self.pcm:
                out.append(("sfx", name))
            pos = m.end()
        rest = text[pos:].strip(" ,")
        if rest:
            out.append(("say", rest))
        return out
