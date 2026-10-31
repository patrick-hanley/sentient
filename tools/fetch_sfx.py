"""Fetch CC0 sound effects from Freesound and prepare them for the toys.

For each entry in SOUNDS: search freesound.org (CC0 only), take the most-downloaded result of a
sensible length, download its high-quality preview, keep the loudest ~2 s, fade the edges,
normalize, convert to 16 kHz mono, and write offline/sfx/<name>.wav plus offline/sfx/index.json
(source, author, license, URL for every sound).

Usage: .venv/bin/python -I tools/fetch_sfx.py [--only name,name] [--force]
Downloads are untrusted data: they land in offline/sfx/_downloads and are only decoded as audio.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "offline" / "sfx"
DL = OUT / "_downloads"
SR = 16000
UA = {"User-Agent": "Mozilla/5.0 (sentient-toys sfx fetcher)"}

# name: (search query, max seconds kept, toy that owns it or None for story sounds, description)
SOUNDS = {
    "dino_roar":   ("dinosaur roar", 2.0, "dyno", "Dyno's roar"),
    "dino_growl":  ("monster growl small", 1.5, "dyno", "Dyno's friendly growl"),
    "penguin":     ("penguin", 1.5, "penny", "Penny's penguin call"),
    "penguin_honk": ("penguin squawk", 1.2, "penny", "Penny's squawk"),
    "sparkle":     ("magic sparkle chime", 1.8, "sage", "Sage's magic sparkle"),
    "whinny":      ("horse whinny", 1.8, "sage", "Sage's unicorn whinny"),
    "knock":       ("door knock", 1.8, None, "knock at the door"),
    "doorbell":    ("doorbell ding dong", 2.0, None, "doorbell"),
    "door_creak":  ("door creak", 2.0, None, "creaky door"),
    "footsteps":   ("footsteps wood", 2.0, None, "footsteps"),
    "birds":       ("birds chirping morning", 2.5, None, "birds chirping"),
    "wind":        ("wind blowing", 2.5, None, "wind blowing"),
    "rain":        ("rain", 2.5, None, "rain"),
    "thunder":     ("thunder", 2.5, None, "thunder"),
    "owl":         ("owl hoot", 2.0, None, "owl hooting"),
    "dog":         ("dog bark", 1.2, None, "dog barking"),
    "cat":         ("cat meow", 1.2, None, "cat meowing"),
    "cow":         ("cow moo", 2.0, None, "cow mooing"),
    "pig":         ("pig oink", 1.5, None, "pig oinking"),
    "sheep":       ("sheep baa", 1.5, None, "sheep baaing"),
    "duck":        ("duck quack", 1.2, None, "duck quacking"),
    "rooster":     ("rooster crow", 2.5, None, "rooster crowing"),
    "frog":        ("frog croak", 1.5, None, "frog croaking"),
    "wolf":        ("wolf howl", 2.5, None, "wolf howling"),
    "bee":         ("bee buzzing", 1.5, None, "bee buzzing"),
    "splash":      ("water splash", 1.2, None, "splash"),
    "bubbles":     ("bubbles", 1.5, None, "bubbles"),
    "clock":       ("clock ticking", 2.0, None, "clock ticking"),
    "school_bell": ("school bell ring", 2.0, None, "school bell"),
    "applause":    ("kids cheering applause", 2.0, None, "cheering"),
    "snore_big":   ("snoring", 3.2, "dyno", "Dyno's snore (asleep)"),
    "snore_cat":   ("cat snoring", 3.2, "sage", "Sage's snore (asleep)"),
    "snore_dog":   ("dog snoring", 3.2, "penny", "Penny's snore (asleep)"),
}
# Halloween set (kid-friendly spooky). Stored on the toys last: they stream if flash is full.
HALLOWEEN = {
    "witch_cackle": ("witch cackle", 2.0, None, "witch cackling"),
    "ghost_boo":    ("boo", 1.5, None, "friendly ghost boo"),
    "ghost_moan":   ("ghost", 2.0, None, "ghost moaning"),
    "bats":         ("bat wings", 1.8, None, "bats flapping"),
    "cauldron":     ("cauldron bubbling", 2.0, None, "bubbling cauldron"),
    "spooky_wind":  ("spooky wind howling", 2.5, None, "spooky wind"),
    "crow":         ("crow caw", 1.5, None, "crow cawing"),
    "bones":        ("skeleton bones rattle", 1.5, None, "rattling bones"),
    "cat_hiss":     ("cat hiss", 1.2, None, "cat hissing"),
    "spooky_organ": ("spooky organ", 2.5, None, "spooky organ"),
    "monster_laugh": ("monster laugh", 2.0, None, "monster laugh"),
}
SETS = {**{n: ("character" if v[2] else "story") for n, v in SOUNDS.items()}, **{n: "halloween" for n in HALLOWEEN}}
SOUNDS.update(HALLOWEEN)


def search(query: str) -> list[dict]:
    url = "https://freesound.org/search/?" + urllib.parse.urlencode(
        {"q": query, "f": 'license:"Creative Commons 0"', "s": "Downloads"})
    page = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf8", "replace")
    out = []
    for block in re.findall(r'<div\s+class="bw-player"(.*?)>', page, re.S):
        a = dict(re.findall(r'data-([a-z0-9-]+)="([^"]*)"', block))
        if "mp3" in a and "sound-id" in a:
            out.append({"id": a["sound-id"], "user": html.unescape(a.get("username", "")),
                        "title": html.unescape(a.get("title", "")), "duration": float(a.get("duration") or 0),
                        "downloads": int(a.get("num-downloads") or 0),
                        "mp3": a["mp3"].replace("-lq.mp3", "-hq.mp3")})
    return out


def prepare(raw: bytes, keep_s: float) -> np.ndarray:
    x, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        n = int(round(len(x) * SR / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    keep = int(keep_s * SR)
    if len(x) > keep:   # loudest window
        env = np.convolve(x * x, np.ones(keep, np.float32), mode="valid")
        start = int(np.argmax(env))
        x = x[start:start + keep]
    fade = min(int(0.03 * SR), len(x) // 4)
    if fade:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    peak = float(np.abs(x).max()) or 1.0
    return (x * (0.7 / peak) * 32767).astype("<i2")   # same peak level as the voices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    DL.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    only = set(filter(None, a.only.split(",")))
    for name, (query, keep_s, toy, desc) in SOUNDS.items():
        if only and name not in only:
            continue
        if name in index and (OUT / f"{name}.wav").exists() and not a.force:
            continue
        try:
            results = [r for r in search(query) if 0.3 <= r["duration"] <= 16]
        except Exception as e:  # noqa: BLE001
            print(f"{name:12} search failed: {e}")
            continue
        if not results:
            print(f"{name:12} no CC0 results for {query!r}")
            continue
        best = max(results[:10], key=lambda r: r["downloads"])
        raw = urllib.request.urlopen(urllib.request.Request(best["mp3"], headers=UA), timeout=60).read()
        (DL / f"{name}_{best['id']}.mp3").write_bytes(raw)
        pcm = prepare(raw, keep_s)
        sf.write(OUT / f"{name}.wav", pcm, SR, subtype="PCM_16")
        index[name] = {"desc": desc, "toy": toy, "set": SETS[name], "seconds": round(len(pcm) / SR, 2), "query": query,
                       "freesound_id": best["id"], "title": best["title"], "author": best["user"],
                       "license": "CC0 1.0", "url": f"https://freesound.org/people/{best['user']}/sounds/{best['id']}/"}
        print(f"{name:12} {len(pcm)/SR:4.1f}s  <- '{best['title']}' by {best['user']} ({best['downloads']} downloads)")
        time.sleep(0.5)   # be polite to freesound.org
    for n in index:   # backfill the set for sounds fetched before sets existed
        index[n].setdefault("set", SETS.get(n, "story"))
    index_path.write_text(json.dumps(index, indent=2))
    total = sum(v["seconds"] for v in index.values())
    print(f"{len(index)} sounds, {total:.0f} s total ≈ {total * 16:.0f} KB as mu-law on a toy")


if __name__ == "__main__":
    main()
