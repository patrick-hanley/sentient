"""Transcripts are speech only. Non-speech vocalizations (snoring, yawns, coughs, laughs, sighs, breathing) are not words:
they are dropped from what the child 'said', and only the label may be logged, as [snoring]. Whisper writes them as
"(snoring)", "[BLANK_AUDIO]", "*coughs*" or spelled out ("zzz", "hee hee"); Gemma may do the same in HEARD."""
from __future__ import annotations

import logging
import re

from . import sfx

log = logging.getLogger("nonspeech")

LABEL = {"snore": "snoring", "yawn": "yawning", "giggle": "laughing", "sigh": "sighing"}
SPELLED = (sfx.ZZZ, sfx.LAUGH, sfx.YAWN, sfx.SIGH)
HUM = re.compile(r"^(?:[\s.,!?…-]|m+h*m*|u+h+m*|h+m+|a+h+|e+r+m*|o+h+)+$", re.I)   # "mm", "hmm", "uh", "ahh" alone are not words


def strip_annotations(text: str) -> tuple[str, list[str]]:
    """-> (speech only, labels of what was removed, e.g. ["snoring"]). Never logs the words themselves."""
    labels: list[str] = []

    def bracket(m):
        w = next(g for g in m.groups() if g).strip().lower().replace("_", " ")
        if w in sfx.VOCAL_TAG:
            labels.append(LABEL[sfx.VOCAL_TAG[w]])
            return " "
        if w in sfx.SILENT_WORDS or m.group(1) is not None and len(w.split()) <= 3:
            labels.append(w)
            return " "
        return m.group(0)

    text = sfx.BRACKET.sub(bracket, text)
    for pat in SPELLED:
        text = pat.sub(lambda m, p=pat: labels.append(LABEL["snore" if p is sfx.ZZZ else "giggle" if p is sfx.LAUGH
                                                           else "yawn" if p is sfx.YAWN else "sigh"]) or " ", text)
    text = " ".join(text.split())
    if HUM.match(text):   # only hums and breaths were left
        if text.strip(" .,!?…-"):
            labels.append("vocalization")
        text = ""
    return text, labels


def clean(text: str) -> str:
    """Speech-only transcript; a removed label is logged as [snoring] etc. (the label only)."""
    out, labels = strip_annotations(text)
    for lab in dict.fromkeys(labels):
        log.info("[%s]", lab)
    return out
