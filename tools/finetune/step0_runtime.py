"""Step zero of the fine-tune plan (gemma-kids-social-model-plan.md): can a runtime that accepts a merged fine-tune still HEAR?

Same spoken clips (synthetic Kokoro voices, never a real child), same system prompt, same turn text, two runtimes on the Jetson:
  A. LiteRT-LM  (.litertlm, what the toys run today; cannot take a LoRA: the shipped decoder has no LoRA inputs)
  B. llama.cpp  (GGUF + mmproj with the audio encoder; a merged fine-tune converts to GGUF with stock tools)
Prints what each one heard (word match against the spoken text) and first-token / full-reply times.
Run on the Jetson with the brain stopped (8 GB):  .venv-brain/bin/python tools/finetune/step0_runtime.py [litert|llama|both]   (STEP0_LORA=adapter.gguf adds a LoRA to llama.cpp)
"""
from __future__ import annotations

import base64, json, os, re, subprocess, sys, tempfile, time, urllib.request, wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from brain import config  # noqa: E402
from brain.director import system_prompt  # noqa: E402

LINES = ["Penny, why is the sky blue?", "Dyno, can we play a game?", "I had pizza for lunch today.", "Sage, what is seven plus five?",
         "My dog is called Biscuit.", "Tell me a story about a dragon.", "I am a little bit sad.", "Penny, how do you spell cat?",
         "What do penguins eat?", "Can you sing a song with me?"]
VOICES = ["af_bella", "am_michael"]
TURN = ("[TOYS HERE] DYNO, SAGE, PENNY (only these toys may speak)\n[SCENE] Nobody's eyes are open.\n"
        "[HEARD BY] PENNY (closest to the child).\n")
LLAMA = "/data/build/llama.cpp/build/bin/llama-server"
PORT = 8091


def clips(d):
    from kokoro_onnx import Kokoro
    k = Kokoro(str(config.KOKORO_DIR / config.KOKORO_MODEL), str(config.KOKORO_DIR / "voices-v1.0.bin"))
    out = []
    for i, t in enumerate(LINES):
        a, sr = k.create(t, voice=VOICES[i % 2], speed=1.0, lang="en-us")
        a = np.asarray(a, np.float32)
        pcm = (np.interp(np.linspace(0, len(a), int(len(a) * 16000 / sr), endpoint=False), np.arange(len(a)), a) * 32767).astype(np.int16)
        pcm = np.concatenate([np.zeros(3200, np.int16), pcm, np.zeros(4800, np.int16)])
        p = str(Path(d) / f"c{i}.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm.tobytes())
        out.append((t, p))
    return out


def words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def score(said, reply):
    m = re.search(r"HEARD:\s*(.*)", reply)
    heard = m.group(1).strip() if m else ""
    w, h = words(said), words(heard)
    return heard, sum(x in h for x in w) / len(w)


def report(name, rows):
    print(f"\n== {name}")
    for said, heard, acc, t1, tt, reply in rows:
        print(f"  {acc*100:3.0f}%  first {t1:4.2f}s  all {tt:4.2f}s  said {said!r} heard {heard!r}\n        reply {reply[:150]!r}")
    print(f"  MEAN heard-word match {np.mean([r[2] for r in rows])*100:.0f}%  first token {np.median([r[3] for r in rows]):.2f}s  "
          f"full reply {np.median([r[4] for r in rows]):.2f}s (medians)", flush=True)


def run_litert(cs):
    from brain import llm
    b = llm.LiteRTBackend(system_prompt())
    b.warm()
    rows = []
    for said, wav in cs:
        b.new_conversation()
        t = time.time(); t1 = None; out = ""
        for d in b.stream(TURN, wav=wav):
            t1 = t1 or time.time() - t
            out += d
        heard, acc = score(said, out)
        rows.append((said, heard, acc, t1 or 0, time.time() - t, out.replace("\n", " | ")))
    report("A. LiteRT-LM " + b.device, rows)


def run_llama(cs, gguf=None, lora=None):
    gguf = gguf or str(config.MODEL_GGUF)
    cmd = [LLAMA, "-m", gguf, "--mmproj", str(config.MMPROJ_GGUF), "--port", str(PORT), "-c", "4096", "-ngl", "99",
           "--reasoning-budget", "0", "-np", "1"] + (["--lora", lora] if lora else [])
    log = open("/tmp/step0-llama.log", "w")
    srv = subprocess.Popen(cmd, stdout=log, stderr=log)
    try:
        for _ in range(120):
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("llama-server did not come up; see /tmp/step0-llama.log")
        rows = []
        for n, (said, wav) in enumerate([cs[0]] + cs):          # the first is a warm-up (prompt cache), not reported
            b64 = base64.b64encode(open(wav, "rb").read()).decode()
            body = {"messages": [{"role": "system", "content": system_prompt()},
                                 {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
                                                              {"type": "text", "text": TURN}]}],
                    "max_tokens": 120, "temperature": 0.8, "stream": True, "cache_prompt": True,
                    "chat_template_kwargs": {"enable_thinking": False}}
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            t = time.time(); t1 = None; out = ""
            with urllib.request.urlopen(req, timeout=120) as r:
                for line in r:
                    line = line.decode().strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    d = json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
                    if d:
                        t1 = t1 or time.time() - t
                        out += d
            if n:
                heard, acc = score(said, out)
                rows.append((said, heard, acc, t1 or 0, time.time() - t, out.replace("\n", " | ")))
        report("B. llama.cpp GPU " + Path(gguf).name + (" + LoRA " + Path(lora).name if lora else ""), rows)
    finally:
        srv.terminate(); srv.wait(10)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    with tempfile.TemporaryDirectory(dir="/dev/shm") as d:      # RAM only, like the brain's audio
        cs = clips(d)
        if which in ("litert", "both"):
            run_litert(cs)
        if which in ("llama", "both"):
            run_llama(cs, gguf=os.environ.get("STEP0_GGUF"), lora=os.environ.get("STEP0_LORA"))
