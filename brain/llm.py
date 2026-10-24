"""Gemma 4 E2B backends.

LiteRTBackend   — LiteRT-LM (Jetson / Pi / Pixel-class). Hears the child's audio directly.
LlamaCppBackend — whisper.cpp transcribes, llama-server runs Gemma GGUF.
GenieXBackend   — VENTUNO Q: whisper transcribes, a local GenieX server runs Gemma GGUF.
Temp WAV/JPEG files are deleted by the caller after streaming and playback finish.
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
        return "".join(getattr(c, "text", "") or "" for c in cs
                       if getattr(c, "type", "text") == "text")
    content = r.get("content", []) if isinstance(r, dict) else []
    if isinstance(content, str):
        return content
    return "".join(c.get("text", "") for c in content
                   if isinstance(c, dict) and c.get("type", "text") == "text")


def _sse(response):
    """Read complete SSE events, including multi-line data and error events."""
    data = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n").lstrip("\ufeff")
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            payload, data = "\n".join(data), []
            if payload == "[DONE]":
                return
            event = json.loads(payload)
            if "error" in event:
                raise RuntimeError(f"Model stream error: {event['error']}")
            yield event
    # Do not silently accept a truncated response or add it to conversation history.
    if data and "\n".join(data) == "[DONE]":
        return
    raise RuntimeError("Model stream ended before [DONE]")


class LiteRTBackend:
    hears_audio = True
    name = "LiteRT-LM"

    def __init__(self, system: str, gpu: bool = True):
        import litert_lm as lm
        self.lm, self.system, self.conv = lm, system, None
        self.device = "gpu" if gpu else "cpu"
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
            self.device = "cpu"
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

    def stream(self, text: str, wav: str | None = None, image: str | None = None):
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
        emitted = False
        for attempt in range(2):
            try:
                send_stream = getattr(self.conv, "send_message_async", None)
                chunks = send_stream(msg) if send_stream else (self.conv.send_message(msg),)
                for chunk in chunks:
                    delta = _text(chunk)
                    if delta:
                        emitted = True
                        yield delta
                self.turns += 1
                return
            except Exception as exc:
                self.new_conversation()
                # Retrying once speech may have been queued could duplicate an answer.
                if emitted or attempt:
                    raise
                log.warning("send failed before output (%s) — retrying with a new conversation", exc)

    def ask(self, text: str, wav: str | None = None, image: str | None = None) -> str:
        return "".join(self.stream(text, wav=wav, image=image))


class LlamaCppBackend:
    hears_audio = False
    name = "llama.cpp"

    @property
    def base_url(self):
        return config.LLAMA_URL

    def request_options(self):
        return {"chat_template_kwargs": {"enable_thinking": False}}

    def __init__(self, system: str):
        self.system, self.history = system, []
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
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
        self._init_transcriber()

    def _init_transcriber(self):
        self.whisper = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
        self.fw = None
        if not self.whisper:
            from faster_whisper import WhisperModel  # CPU int8, fully local
            self.fw = WhisperModel(str(config.OFFLINE / "faster-whisper-base.en"), device="cpu", compute_type="int8")

    def _healthy(self) -> bool:
        try:
            with self.http.open(self.base_url + "/health", timeout=1) as response:
                return response.status == 200
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

    def stream(self, text: str, wav: str | None = None, image: str | None = None):
        content = text
        if image:
            with open(image, "rb") as source:
                b64 = base64.b64encode(source.read()).decode()
            content = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                       {"type": "text", "text": text}]
        msgs = [{"role": "system", "content": self.system}] + self.history[-2 * config.RESET_AFTER_TURNS:] \
            + [{"role": "user", "content": content}]
        body = json.dumps({"messages": msgs, "max_tokens": 120, "temperature": 0.8,
                           "stream": True, **self.request_options()}).encode()
        req = urllib.request.Request(self.base_url + "/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        parts = []
        with self.http.open(req, timeout=120) as response:
            for event in _sse(response):
                for choice in event.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    reason = choice.get("finish_reason")
                    if reason and reason != "stop":
                        raise RuntimeError(f"Model reply did not complete: {reason}")
                    # The separate reasoning/tool channels are never sent to speech.
                    delta = choice.get("delta", {}).get("content")
                    if isinstance(delta, str) and delta:
                        parts.append(delta)
                        yield delta
        self.history += [{"role": "user", "content": text},
                         {"role": "assistant", "content": "".join(parts)}]
        self.history = self.history[-2 * config.RESET_AFTER_TURNS:]

    def ask(self, text: str, wav: str | None = None, image: str | None = None) -> str:
        return "".join(self.stream(text, wav=wav, image=image))


class GenieXBackend(LlamaCppBackend):
    """Connect to an already running server; never silently start a CPU fallback."""
    name = "GenieX"
    device = "server-configured (verify NPU in GenieX)"

    @property
    def base_url(self):
        return config.GENIEX_URL

    def request_options(self):
        return {"model": config.GENIEX_MODEL, "enable_think": False,
                "reasoning_format": "deepseek"}

    def __init__(self, system: str):
        self.system, self.history, self.server = system, [], None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with self.http.open(self.base_url + "/v1/models", timeout=5) as response:
                models = json.load(response)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"GenieX is unavailable at {self.base_url}. Start 'geniex serve --compute npu' on the board.") from exc
        available = {item.get("id") for item in models.get("data", [])}
        if config.GENIEX_MODEL not in available:
            raise RuntimeError(f"GenieX model {config.GENIEX_MODEL!r} is not cached. Run 'geniex pull' or set SENTIENT_GENIEX_MODEL to an id from /v1/models.")
        self._init_transcriber()


def make_backend(kind: str, system: str, gpu: bool):
    if kind == "geniex":
        return GenieXBackend(system)
    if kind in ("auto", "litert"):
        try:
            return LiteRTBackend(system, gpu=gpu)
        except ImportError:
            if kind == "litert":
                raise
            log.warning("litert_lm not installed here — using llama.cpp fallback")
    return LlamaCppBackend(system)
