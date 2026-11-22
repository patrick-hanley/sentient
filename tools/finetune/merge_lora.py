"""Merge a PEFT LoRA adapter into the checkpoint's weights, one tensor at a time (fits in a few GB of RAM, no GPU).

  python merge_lora.py <checkpoint dir with model.safetensors> <adapter dir> <out dir>

Why: an adapter trained on the original weights does not fit a separately made 4-bit GGUF (the rounding moves the weights
it was trained against). Merge first, then convert and quantize the merged model, so both are rounded together:
  convert_hf_to_gguf.py <out dir> --outtype f16 --outfile merged-f16.gguf
  llama-quantize merged-f16.gguf merged-Q4_0.gguf Q4_0
The audio/vision file (mmproj) is untouched by training and stays the same.
"""
from __future__ import annotations

import json, shutil, struct, sys
from pathlib import Path

import torch
from safetensors import safe_open

DT = {"BF16": (torch.bfloat16, 2), "F16": (torch.float16, 2), "F32": (torch.float32, 4)}


def main():
    base, adapter, out = map(Path, sys.argv[1:4])
    cfg = json.loads((adapter / "adapter_config.json").read_text())
    scale = cfg["lora_alpha"] / cfg["r"]
    lora = {}
    with safe_open(str(adapter / "adapter_model.safetensors"), "pt") as f:
        for k in f.keys():
            name, ab = k.removeprefix("base_model.model.").rsplit(".lora_", 1)
            lora.setdefault(name + ".weight", {})[ab[0]] = f.get_tensor(k).float()
    out.mkdir(parents=True, exist_ok=True)
    for p in base.iterdir():
        if p.is_file() and p.name != "model.safetensors":
            shutil.copy(p, out / p.name)
    src = base / "model.safetensors"
    with open(src, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        head = f.read(n)
    header = json.loads(head)
    missing = set(lora) - set(header)
    assert not missing, f"adapter names not in the checkpoint: {sorted(missing)[:3]}"
    names = sorted((k for k in header if k != "__metadata__"), key=lambda k: header[k]["data_offsets"][0])
    done, biggest = 0, 0.0
    with open(src, "rb") as f, open(out / "model.safetensors", "wb") as g:
        g.write(struct.pack("<Q", n))
        g.write(head)                                            # same header: shapes, dtypes and offsets do not change
        for k in names:
            a, b = header[k]["data_offsets"]
            f.seek(8 + n + a)
            raw = f.read(b - a)
            if k in lora:
                dt, _ = DT[header[k]["dtype"]]
                w = torch.frombuffer(bytearray(raw), dtype=dt).reshape(header[k]["shape"]).float()
                d = (lora[k]["B"] @ lora[k]["A"]) * scale
                biggest = max(biggest, float(d.norm() / w.norm()))
                bits = torch.int16 if DT[header[k]["dtype"]][1] == 2 else torch.int32      # numpy has no bfloat16
                raw = (w + d).to(dt).contiguous().view(bits).numpy().tobytes()
                assert len(raw) == b - a
                done += 1
            g.write(raw)
    assert done == len(lora)
    print(f"merged {done} weight matrices (scale {scale}); largest change {100 * biggest:.1f}% of a matrix's size; wrote {out}")


if __name__ == "__main__":
    main()
