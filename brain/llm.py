"""Gemma 4 E2B backends.

LiteRTBackend   — LiteRT-LM (Jetson / Pi / Pixel-class). Hears the child's audio directly.
LlamaCppBackend — Intel-Mac fallback: whisper.cpp transcribes, llama-server runs Gemma GGUF.
Both are fully local. Temp WAV/JPEG files are deleted by the caller right after ask().
"""
from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
import time
import urllib.request

from . import config

log = logging.getLogger("llm")


def _enter(obj):
    enter = getattr(obj, "__enter__", None)
    return (enter() or obj) if enter else obj


def _text(r) -> str:
    cs = getattr(r, "contents", None)
    if cs:
        return "".join(getattr(c, "text", "") or "" for c in cs)
    content = r.get("content", []) if isinstance(r, dict) else []
    if isinstance(content, str):
        return content
    return "".join(c.get("text", "") for c in content if isinstance(c, dict))


class LiteRTBackend:
    hears_audio = True
    name = "LiteRT-LM"

    def __init__(self, system: str, gpu: bool = True):
        import litert_lm as lm
        self.lm, self.system, self.conv = lm, system, None
        lm.set_min_log_severity(lm.LogSeverity.ERROR)
        main_be = lm.Backend.GPU() if gpu else lm.Backend.CPU()
        kw = dict(backend=main_be, audio_backend=lm.Backend.CPU(), vision_backend=main_be,
                  max_num_images=1, cache_dir=str(config.DATA / "litert-cache"))
        t = time.time()
        try:
            self.engine = _enter(lm.Engine(str(config.MODEL_LITERT), **kw))
        except Exception as e:  # noqa: BLE001
            if not gpu:
                raise
            log.warning("GPU engine failed (%s) — retrying on CPU", e)
            kw.update(backend=lm.Backend.CPU(), vision_backend=lm.Backend.CPU())
            self.engine = _enter(lm.Engine(str(config.MODEL_LITERT), **kw))
        log.info("LiteRT-LM engine ready in %.1fs", time.time() - t)
        self.new_conversation()

    def new_conversation(self):
        if self.conv is not None and hasattr(self.conv, "__exit__"):
            try:
                self.conv.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        # Gemma 4 thinks by default: ~8 s of hidden reasoning per turn. Off for snappy toys.
        self.conv = _enter(self.engine.create_conversation(
            messages=[self.lm.Message.system(self.system)],
            thinking_config=self.lm.ThinkingConfig(enable_thinking=False),
            max_output_tokens=120))
        self.turns = 0

    def ask(self, text: str, wav: str | None = None, image: str | None = None) -> str:
        if self.turns >= config.RESET_AFTER_TURNS:
            self.new_conversation()
        parts = []
        if wav:
            parts.append(self.lm.Content.AudioFile(absolute_path=wav))
        if image:
            img_cls = getattr(self.lm.Content, "ImageFile", None)
            if img_cls:
                parts.append(img_cls(absolute_path=image))
        parts.append(text)
        msg = self.lm.Contents.of(*parts) if len(parts) > 1 else text
        try:
            r = self.conv.send_message(msg)
        except Exception as e:  # noqa: BLE001 — context full or similar: start fresh once
            log.warning("send failed (%s) — new conversation", e)
            self.new_conversation()
            r = self.conv.send_message(msg)
        self.turns += 1
        return _text(r)


class LlamaCppBackend:
    hears_audio = False
    name = "llama.cpp (Mac fallback)"

    def __init__(self, system: str):
        self.system, self.history = system, []
        self.server = None
        if not self._healthy():
            exe = shutil.which("llama-server") or next(
                (str(x) for x in sorted(config.OFFLINE.glob("llamacpp-*/*/llama-server"))), None)
            if not exe:
                raise RuntimeError("llama-server not found (offline/llamacpp-macos-x64/ or brew)")
            cmd = [exe, "-m", str(config.MODEL_GGUF), "--port", config.LLAMA_URL.rsplit(":", 1)[1], "-c", "4096"]
            if config.MMPROJ_GGUF.exists():
                cmd += ["--mmproj", str(config.MMPROJ_GGUF)]
            log.info("starting %s", " ".join(cmd))
            self.server = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(240):
                if self._healthy():
                    break
                time.sleep(1)
            else:
                raise RuntimeError("llama-server did not come up")
        self.whisper = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
        self.fw = None
        if not self.whisper:
            from faster_whisper import WhisperModel  # CPU int8, fully local
            self.fw = WhisperModel(str(config.OFFLINE / "faster-whisper-base.en"), device="cpu", compute_type="int8")

    def _healthy(self) -> bool:
        try:
            return urllib.request.urlopen(config.LLAMA_URL + "/health", timeout=1).status == 200
        except OSError:
            return False

    def transcribe(self, wav: str) -> str:
        if self.fw is not None:
            segs, _ = self.fw.transcribe(wav, language="en", beam_size=1, vad_filter=True,
                                         condition_on_previous_text=False)
            # drop segments Whisper itself thinks are not speech / is guessing at
            return " ".join(s.text for s in segs if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0).strip()
        out = subprocess.run([self.whisper, "-m", str(config.WHISPER_MODEL), "-f", wav, "-nt", "-np", "-l", "en"],
                             capture_output=True, text=True, timeout=60).stdout
        return " ".join(out.split()).strip()

    def ask(self, text: str, wav: str | None = None, image: str | None = None) -> str:
        content = text
        if image:
            b64 = base64.b64encode(open(image, "rb").read()).decode()
            content = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                       {"type": "text", "text": text}]
        msgs = [{"role": "system", "content": self.system}] + self.history[-2 * config.RESET_AFTER_TURNS:] \
            + [{"role": "user", "content": content}]
        body = json.dumps({"messages": msgs, "max_tokens": 120, "temperature": 0.8,
                           "chat_template_kwargs": {"enable_thinking": False}}).encode()
        req = urllib.request.Request(config.LLAMA_URL + "/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        reply = json.loads(urllib.request.urlopen(req, timeout=120).read())["choices"][0]["message"]["content"]
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        return reply


def make_backend(kind: str, system: str, gpu: bool):
    if kind in ("auto", "litert"):
        try:
            return LiteRTBackend(system, gpu=gpu)
        except ImportError:
            if kind == "litert":
                raise
            log.warning("litert_lm not installed here — using llama.cpp fallback")
    return LlamaCppBackend(system)
