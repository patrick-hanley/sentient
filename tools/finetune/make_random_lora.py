"""Step zero helper: an UNTRAINED LoRA (small random numbers) on Gemma 4 E2B's language layers only, in PEFT format, built
from the tensor shapes in the checkpoint's safetensors header (no weights loaded: fits the Jetson). It exists to prove the
adapter -> GGUF -> llama-server path before any real training; it is not a model anyone should use.

  python make_random_lora.py <safetensors header .json> <out dir> [rank] [std]
"""
import json, sys
from pathlib import Path

import numpy as np
from safetensors.numpy import save_file

SHARED_KV_FROM = 15   # Gemma 4 E2B: layers 15-34 share the KV cache (llama.cpp: no blk.15+.attn_k / attn_v)
MODULES = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
header, out = json.load(open(sys.argv[1])), Path(sys.argv[2])
rank = int(sys.argv[3]) if len(sys.argv) > 3 else 8
std = float(sys.argv[4]) if len(sys.argv) > 4 else 0.01
rng = np.random.default_rng(0)
tensors = {}
for name, meta in header.items():
    if not name.startswith("model.language_model.layers.") or not name.endswith(".weight"):
        continue
    mod, layer = name.split(".")[-2], int(name.split(".")[3])
    if mod not in MODULES:
        continue
    if mod in ("k_proj", "v_proj") and layer >= SHARED_KV_FROM:
        continue                      # these layers reuse an earlier layer's keys/values: the GGUF has no such tensors
    o, i = meta["shape"]
    base = "base_model.model." + name[:-len(".weight")]
    tensors[base + ".lora_A.weight"] = (rng.standard_normal((rank, i)) * std).astype(np.float32)
    tensors[base + ".lora_B.weight"] = (rng.standard_normal((o, rank)) * std).astype(np.float32)
out.mkdir(parents=True, exist_ok=True)
save_file(tensors, str(out / "adapter_model.safetensors"))
(out / "adapter_config.json").write_text(json.dumps({
    "peft_type": "LORA", "task_type": "CAUSAL_LM", "base_model_name_or_path": "google/gemma-4-E2B-it",
    "r": rank, "lora_alpha": rank, "lora_dropout": 0.0, "bias": "none", "fan_in_fan_out": False,
    "target_modules": list(MODULES), "inference_mode": True, "use_rslora": False, "use_dora": False}, indent=1))
print(len(tensors) // 2, "modules, rank", rank, "->", out)
