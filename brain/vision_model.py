"""Pluggable image-to-text backends for "what is that object?".

config.VISION_MODEL (env SENTIENT_VISION_MODEL) picks one:

  gemma     (default) no separate model: the JPEG is attached to the main Gemma prompt
            (brain/llm.py), so make_vision() returns None and callers keep that path.
  llamacpp  a VLM served by an OpenAI-compatible llama.cpp `llama-server` (any GGUF + mmproj:
            Qwen3-VL-2B, SmolVLM-500M, ...). URL: SENTIENT_VISION_URL (default http://127.0.0.1:8082).
  florence  Florence-2 captioner in-process via transformers (needs torch, einops, timm).
  none/off  disabled (returns None too).

Backends are imported lazily and construct without loading anything heavy, so the brain starts
even when their dependencies are missing; a missing dependency or server only fails (or returns "")
on describe(). See docs/vision.md for the benchmark behind the choices.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import urllib.request

log = logging.getLogger("vision_model")

DEFAULT_QUESTION = "Name the main object in one short sentence a child would understand."
KINDS = ("gemma", "llamacpp", "florence", "none")


class VisionModel:
    name: str = "base"

    def describe(self, jpeg: bytes, question: str = "") -> str:
        """Short plain-English answer about the image; "" if the backend is unavailable."""
        raise NotImplementedError


class LlamaCppVision(VisionModel):
    """Talks to llama-server's /v1/chat/completions with the image inline (base64 data URL)."""
    name = "llamacpp"

    def __init__(self, url: str | None = None, timeout: float = 30.0, max_tokens: int = 48):
        self.url = (url or os.environ.get("SENTIENT_VISION_URL", "http://127.0.0.1:8082")).rstrip("/")
        self.timeout, self.max_tokens = timeout, max_tokens

    def describe(self, jpeg: bytes, question: str = "") -> str:
        try:
            body = {"messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
                {"type": "text", "text": question or DEFAULT_QUESTION}]}],
                "max_tokens": self.max_tokens, "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False}}
            req = urllib.request.Request(self.url + "/v1/chat/completions", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except Exception as e:  # server down, bad reply: the toy just says it can't see
            log.warning("llamacpp vision failed: %s", e)
            return ""


class FlorenceVision(VisionModel):
    """Florence-2 <CAPTION> (0.23B base). Ignores `question`: it is a fixed-task captioner."""
    name = "florence"

    def __init__(self, repo: str | None = None):
        self.repo = repo or os.environ.get("SENTIENT_VISION_REPO", "microsoft/Florence-2-base")
        self._m = self._p = self._dev = None

    def _load(self):
        import torch
        import transformers.dynamic_module_utils as dmu
        from transformers import AutoModelForCausalLM, AutoProcessor
        orig = dmu.get_imports
        dmu.get_imports = lambda f: [i for i in orig(f) if i != "flash_attn"]  # optional dep, not on Jetson/Mac
        self._dev = "cuda" if torch.cuda.is_available() else "cpu"
        dt = torch.float16 if self._dev == "cuda" else torch.float32
        self._m = AutoModelForCausalLM.from_pretrained(self.repo, trust_remote_code=True, torch_dtype=dt).to(self._dev).eval()
        self._p = AutoProcessor.from_pretrained(self.repo, trust_remote_code=True)

    def describe(self, jpeg: bytes, question: str = "") -> str:
        try:
            import torch
            from PIL import Image
            if self._m is None:
                self._load()
            img = Image.open(io.BytesIO(jpeg)).convert("RGB")
            inp = self._p(text="<CAPTION>", images=img, return_tensors="pt").to(self._dev, self._m.dtype)
            with torch.no_grad():
                ids = self._m.generate(input_ids=inp["input_ids"], pixel_values=inp["pixel_values"],
                                       max_new_tokens=40, num_beams=3, do_sample=False)
            return self._p.batch_decode(ids, skip_special_tokens=True)[0].strip()
        except Exception as e:
            log.warning("florence vision failed: %s", e)
            return ""


_BACKENDS = {"llamacpp": LlamaCppVision, "florence": FlorenceVision}


def make_vision(kind: str | None = None) -> VisionModel | None:
    """Backend for `kind` (default config.VISION_MODEL). None means "no separate model":
    "gemma" (image goes into the main Gemma prompt), "none"/"off"/"", or an unknown name (logged)."""
    if kind is None:
        from . import config
        kind = config.VISION_MODEL
    kind = (kind or "").strip().lower()
    if kind in ("", "gemma", "none", "off"):
        return None
    cls = _BACKENDS.get(kind)
    if cls is None:
        log.warning("unknown SENTIENT_VISION_MODEL %r (known: %s); using Gemma's own vision", kind, ", ".join(KINDS))
        return None
    return cls()
