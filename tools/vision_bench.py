#!/usr/bin/env python3
"""Benchmark vision-to-text models on toy-camera-quality household images.

    python tools/vision_bench.py --models gemma,smolvlm-500m,qwen3vl-2b,florence2-base,moondream2
    python tools/vision_bench.py --jetson --models gemma,smolvlm-500m,qwen3vl-2b   # on the Jetson

Scores per model: (a) hit rate (ground truth label or any synonym appears,
normalised substring match, in the model's one-sentence answer) and (b) latency
median / p90 per image (first image is a warm-up and excluded) and peak RSS.
GGUF models run through llama-server (llama.cpp) so every candidate is measured
the same way; the RSS figure is the server process tree. Transformers models run
in-process. Results go to stdout and to a markdown/JSON file (see --out).
Mac numbers are CPU-only and only meaningful relative to each other.

Models need to be downloaded first; paths come from --models-dir (default
$SENTIENT_BENCH_MODELS or ./models) with the HF layout in MODELS below, or the
repo's offline/gguf for Gemma. Missing model => row reported as 'not run'.
"""
import argparse, base64, io, json, os, platform, re, shutil, signal, socket, statistics, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SET = Path(__file__).resolve().parent / "vision_set"
PROMPT = "Name the main object in one short sentence a child would understand."

# name -> spec.  kind "gguf": (model, mmproj) relative to models dir.  kind "hf": transformers repo id.
MODELS = {
    "gemma": dict(kind="gguf", label="Gemma 4 E2B Q4_0 (+mmproj Q8)", params="5.1B (2.3B eff.)",
                  model="@offline/gguf/gemma-4-E2B-it-Q4_0.gguf", mmproj="@offline/gguf/mmproj-gemma-4-E2B-it-Q8_0.gguf"),
    "smolvlm-256m": dict(kind="gguf", label="SmolVLM-256M Q8", params="0.26B",
                         model="SmolVLM-256M-Instruct-GGUF/SmolVLM-256M-Instruct-Q8_0.gguf",
                         mmproj="SmolVLM-256M-Instruct-GGUF/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf"),
    "smolvlm-500m": dict(kind="gguf", label="SmolVLM-500M Q8", params="0.5B",
                         model="SmolVLM-500M-Instruct-GGUF/SmolVLM-500M-Instruct-Q8_0.gguf",
                         mmproj="SmolVLM-500M-Instruct-GGUF/mmproj-SmolVLM-500M-Instruct-Q8_0.gguf"),
    "qwen3vl-2b": dict(kind="gguf", label="Qwen3-VL-2B Q8", params="2.1B",
                       model="Qwen3-VL-2B-Instruct-GGUF/Qwen3-VL-2B-Instruct-Q8_0.gguf",
                       mmproj="Qwen3-VL-2B-Instruct-GGUF/mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf"),
    "qwen25vl-3b": dict(kind="gguf", label="Qwen2.5-VL-3B Q4_K_M", params="3.8B",
                        model="Qwen2.5-VL-3B-Instruct-GGUF/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
                        mmproj="Qwen2.5-VL-3B-Instruct-GGUF/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"),
    "florence2-base": dict(kind="hf", label="Florence-2-base (fp32)", params="0.23B", repo="microsoft/Florence-2-base"),
    "florence2-large": dict(kind="hf", label="Florence-2-large (fp32)", params="0.77B", repo="microsoft/Florence-2-large"),
    "moondream2": dict(kind="hf", label="Moondream2 (fp32)", params="1.9B", repo="vikhyatk/moondream2", revision="2024-08-26"),
}


def norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def hit(text, entry):
    t = " " + norm(text) + " "
    keys = {norm(entry["label"]), *map(norm, entry.get("synonyms", []))}
    keys = {k[:-1] if len(k) > 3 and k.endswith("s") else k for k in keys}   # "scissors" also accepts "a scissor"
    return any(k and k in t for k in keys)


def tree_rss(pid):
    import psutil
    try:
        p = psutil.Process(pid)
        return sum(c.memory_info().rss for c in [p, *p.children(recursive=True)])
    except Exception:
        return 0


class RssSampler(threading.Thread):
    def __init__(self, pid):
        super().__init__(daemon=True); self.pid, self.peak, self.stop = pid, 0, False
    def run(self):
        while not self.stop:
            self.peak = max(self.peak, tree_rss(self.pid)); time.sleep(0.1)


# ---------------------------------------------------------------- backends
a_timeout = 180   # seconds per image; a hang is reported as a miss, not a stall


class GgufRunner:
    def __init__(self, spec, a):
        import requests
        self.requests = requests
        base = Path(a.models_dir)
        def res(p): return Path(os.environ.get("SENTIENT_OFFLINE", ROOT / "offline")) / p[len("@offline/"):] if p.startswith("@") else base / p
        m, mm = res(spec["model"]), res(spec["mmproj"])
        for f in (m, mm):
            if not f.exists(): raise FileNotFoundError(f)
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        cmd = [a.llama_server, "-m", str(m), "--mmproj", str(mm), "--port", str(self.port), "-c", "4096",
               "--temp", "0", "-ngl", str(a.ngl), "--no-warmup", "-np", "1"]
        if "qwen" in spec["model"].lower(): cmd += ["--image-min-tokens", "256"]   # llama.cpp default is too low for Qwen-VL accuracy; 256 keeps it fast
        if not a.jetson: cmd += ["--no-mmproj-offload"]
        self.log = tempfile.NamedTemporaryFile("w+", suffix=".log")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT)
        self.rss = RssSampler(self.proc.pid); self.rss.start()
        for _ in range(600):
            if self.proc.poll() is not None: raise RuntimeError("llama-server exited: " + open(self.log.name).read()[-400:])
            try:
                if requests.get(f"http://127.0.0.1:{self.port}/health", timeout=1).status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else: raise TimeoutError("llama-server not ready")

    def describe(self, jpeg, prompt):
        b64 = base64.b64encode(jpeg).decode()
        body = {"messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": prompt}]}], "max_tokens": 48, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
        r = self.requests.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", json=body, timeout=a_timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def peak_rss(self): return self.rss.peak
    def close(self):
        self.rss.stop = True; self.proc.send_signal(signal.SIGINT)
        try: self.proc.wait(10)
        except Exception: self.proc.kill()


class HfRunner:
    def __init__(self, spec, a):
        import torch
        from PIL import Image
        self.Image, self.torch, self.spec = Image, torch, spec
        torch.set_num_threads(os.cpu_count() or 4)
        self.dev = "cuda" if a.jetson and torch.cuda.is_available() else "cpu"
        self.rss = RssSampler(os.getpid()); self.rss.start()
        from transformers import AutoModelForCausalLM, AutoProcessor, AutoTokenizer
        rev = spec.get("revision")
        dtype = torch.float16 if self.dev == "cuda" else torch.float32
        if "florence" in spec["repo"].lower():
            _patch_flash_attn()
            self.model = AutoModelForCausalLM.from_pretrained(spec["repo"], trust_remote_code=True, torch_dtype=dtype).to(self.dev).eval()
            self.proc = AutoProcessor.from_pretrained(spec["repo"], trust_remote_code=True)
            self.mode = "florence"
        else:
            self.model = AutoModelForCausalLM.from_pretrained(spec["repo"], revision=rev, trust_remote_code=True, torch_dtype=dtype).to(self.dev).eval()
            self.tok = AutoTokenizer.from_pretrained(spec["repo"], revision=rev)
            self.mode = "moondream"

    def describe(self, jpeg, prompt):
        img = self.Image.open(io.BytesIO(jpeg)).convert("RGB")
        with self.torch.no_grad():
            if self.mode == "florence":
                # Florence-2 ignores free-form prompts; <CAPTION> is its short-description task.
                inp = self.proc(text="<CAPTION>", images=img, return_tensors="pt").to(self.dev, self.model.dtype)
                ids = self.model.generate(input_ids=inp["input_ids"], pixel_values=inp["pixel_values"], max_new_tokens=40, num_beams=3, do_sample=False)
                return self.proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
            return self.model.query(img, prompt, self.tok)["answer"].strip() if hasattr(self.model, "query") else \
                self.model.answer_question(self.model.encode_image(img), prompt, self.tok)

    def peak_rss(self): return self.rss.peak
    def close(self): self.rss.stop = True


def _patch_flash_attn():
    """Florence-2's remote code imports flash_attn unconditionally; it is not needed (and not installable on Mac)."""
    from unittest.mock import patch
    from transformers.dynamic_module_utils import get_imports
    orig = get_imports
    def fixed(f):
        return [i for i in orig(f) if i != "flash_attn"]
    import transformers.dynamic_module_utils as dmu
    dmu.get_imports = fixed


# ---------------------------------------------------------------- main
def _warmup_jpeg():
    import random
    from PIL import Image
    r = random.Random(1)
    im = Image.new("RGB", (320, 240))
    im.putdata([(r.randrange(40), r.randrange(60), r.randrange(40)) for _ in range(320 * 240)])
    b = io.BytesIO(); im.save(b, "JPEG", quality=50); return b.getvalue()


def run_model(name, entries, a):
    spec = MODELS[name]
    runner = (GgufRunner if spec["kind"] == "gguf" else HfRunner)(spec, a)
    rows, lat = [], []
    try:
        runner.describe(_warmup_jpeg(), a.prompt)                          # warm-up on a synthetic image, not scored
        for e in entries:
            jpeg = (SET / e["file"]).read_bytes()
            t = time.perf_counter()
            try: ans = runner.describe(jpeg, a.prompt)
            except Exception as ex: ans = f"<error {type(ex).__name__}>"
            dt = time.perf_counter() - t
            lat.append(dt); rows.append(dict(file=e["file"], label=e["label"], answer=ans, hit=hit(ans, e), s=round(dt, 3)))
            print(f"  {name:15s} {e['label']:14s} {'OK ' if rows[-1]['hit'] else 'MISS'} {dt:5.1f}s  {ans[:80]!r}", flush=True)
        peak = runner.peak_rss()
    finally:
        runner.close()
    lat_s = sorted(lat)
    return dict(model=name, label=spec["label"], params=spec["params"], n=len(rows),
                hits=sum(r["hit"] for r in rows), hit_rate=sum(r["hit"] for r in rows) / len(rows),
                median_s=statistics.median(lat), p90_s=lat_s[min(len(lat_s) - 1, int(0.9 * len(lat_s)))],
                peak_rss_mb=round(peak / 2**20), rows=rows)


def table(results, device):
    out = [f"Device: {device}. Prompt: \"{PROMPT}\". Latency excludes a warm-up call.", "",
           "| Model | Params | Hit rate | Median s | p90 s | Peak RSS MB |", "|---|---|---|---|---|---|"]
    for r in results:
        if "error" in r: out.append(f"| {r['label']} | {r['params']} | not run: {r['error']} | | | |")
        else: out.append(f"| {r['label']} | {r['params']} | {r['hits']}/{r['n']} ({r['hit_rate']:.0%}) | {r['median_s']:.2f} | {r['p90_s']:.2f} | {r['peak_rss_mb']} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="gemma,smolvlm-500m,qwen3vl-2b,florence2-base,moondream2")
    ap.add_argument("--models-dir", default=os.environ.get("SENTIENT_BENCH_MODELS", "models"))
    ap.add_argument("--llama-server", default=os.environ.get("LLAMA_SERVER") or shutil.which("llama-server") or
                    str(next((ROOT.parent.parent / "sentient/offline/llamacpp-macos-x64").glob("*/llama-server"), "llama-server")))
    ap.add_argument("--jetson", action="store_true", help="GPU run: llama-server -ngl 99 (full offload incl. mmproj), torch on cuda")
    ap.add_argument("--ngl", type=int, default=None)
    ap.add_argument("--limit", type=int, default=0, help="only first N images (smoke test)")
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--rescore", metavar="JSON", help="re-score a saved results .json against the current manifest (no models run)")
    ap.add_argument("--out", default=None, help="results base name (writes .md and .json); default tools/vision_results_<device>")
    a = ap.parse_args()
    a.ngl = a.ngl if a.ngl is not None else (99 if a.jetson else 0)
    device = ("Jetson Orin Nano Super (GPU)" if a.jetson else f"{platform.node()} {platform.machine()} CPU")
    entries = json.load(open(SET / "manifest.json"))["images"]
    if a.rescore:
        saved = json.load(open(a.rescore)); by = {e["file"]: e for e in entries}
        for r in saved["results"]:
            if "error" in r: continue
            for row in r["rows"]: row["hit"] = hit(row["answer"], by[row["file"]])
            r["hits"] = sum(row["hit"] for row in r["rows"]); r["hit_rate"] = r["hits"] / r["n"]
        Path(a.rescore).write_text(json.dumps(saved, indent=1)); print(table(saved["results"], saved["device"])); return
    if a.limit: entries = entries[:a.limit]
    results = []
    for name in a.models.split(","):
        spec = MODELS[name]
        print(f"== {name}", flush=True)
        try: results.append(run_model(name, entries, a))
        except Exception as e:
            results.append(dict(model=name, label=spec["label"], params=spec["params"], error=f"{type(e).__name__}: {str(e)[:120]}"))
            print("  not run:", results[-1]["error"], flush=True)
    md = table(results, device); print("\n" + md)
    base = a.out or str(ROOT / "tools" / ("vision_results_jetson" if a.jetson else "vision_results_mac"))
    Path(base + ".md").write_text(md + "\n"); Path(base + ".json").write_text(json.dumps(dict(device=device, results=results), indent=1))


if __name__ == "__main__":
    main()
