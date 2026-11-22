"""LoRA fine-tune of Gemma 4 E2B on rendered scenes (tools/finetune/scenes.py render). Runs on one 16 GB GPU (Colab T4).

  python train_lora.py --data train.jsonl --val train-val.jsonl --out adapter [--epochs 3] [--rank 16] [--lr 2e-4]

Text only: the audio and vision towers are never loaded into the optimizer, and only the language layers get LoRA weights.
Layers 15-34 share the key/value cache, so k_proj / v_proj there are skipped (llama.cpp has no such tensors and refuses an
adapter that names them). Loss is taken on the toys' replies only, never on the system prompt or the child's turn.
The adapter is saved in PEFT format with the checkpoint's tensor names, ready for llama.cpp's convert_lora_to_gguf.py.
"""
from __future__ import annotations

import argparse, json, math, random, re, time
from pathlib import Path

import torch

SHARED_KV_FROM = 15
TARGETS = (r"(?!.*(?:audio|vision)).*layers\.(?:"
           r"\d+\.(?:self_attn\.(?:q_proj|o_proj)|mlp\.(?:gate_proj|up_proj|down_proj))"
           r"|(?:\d|1[0-4])\.self_attn\.(?:k_proj|v_proj))")


def encode(tok, messages, max_len):
    """ids + labels (-100 outside the assistant turns). Spans come from the chat template itself: the text of
    messages[:i] + generation prompt is a prefix of the text of messages[:i+1]."""
    def ids(ms, gen=False):
        return tok.apply_chat_template(ms, tokenize=True, add_generation_prompt=gen, return_dict=True)["input_ids"]
    skip = {i for i, m in enumerate(messages) if m.get("train") is False}     # history turns: read, not trained on
    messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    full = ids(messages)
    labels = [-100] * len(full)
    for i, m in enumerate(messages):
        if m["role"] != "assistant" or i in skip:
            continue
        pre, upto = ids(messages[:i], gen=True), ids(messages[:i + 1])
        if full[:len(pre)] != pre or full[:len(upto)] != upto:
            raise ValueError("chat template is not prefix-consistent")
        labels[len(pre):len(upto)] = full[len(pre):len(upto)]
    if len(full) > max_len:
        return None
    return torch.tensor(full), torch.tensor(labels)


def load(path, tok, max_len):
    out, dropped = [], 0
    for line in Path(path).read_text().splitlines():
        if line.strip():
            e = encode(tok, json.loads(line)["messages"], max_len)
            dropped += e is None
            if e:
                out.append(e)
    print(f"{path}: {len(out)} examples, {dropped} over {max_len} tokens dropped, "
          f"longest {max(len(x[0]) for x in out)}, trained tokens {sum(int((x[1] != -100).sum()) for x in out)}", flush=True)
    return out


def lm_loss(model, x, y):
    """Cross-entropy on the labelled positions only. The stock forward builds logits for every token over a 262k vocabulary
    (over 2 GB for one 2,300-token scene, out of memory on a T4); here the output layer runs on the toys' reply tokens only."""
    core = model.base_model.model                      # Gemma4ForConditionalGeneration under the PEFT wrapper
    x, y = x.cuda(), y.cuda()
    with torch.autocast("cuda", dtype=torch.float16):
        h = core.model(input_ids=x[None]).last_hidden_state[0]
        pos = (y[1:] != -100).nonzero(as_tuple=True)[0]        # hidden state t predicts token t+1
        logits = core.lm_head(h[pos])
    logits = logits.float()
    cap = getattr(core.config, "final_logit_softcapping", None) or getattr(getattr(core.config, "text_config", None), "final_logit_softcapping", None)
    if cap:
        logits = torch.tanh(logits / cap) * cap
    return torch.nn.functional.cross_entropy(logits, y[1:][pos])


@torch.no_grad()
def val_loss(model, data):
    model.eval()
    tot = n = 0
    for x, y in data:
        k = int((y != -100).sum())
        loss = lm_loss(model, x, y)
        tot, n = tot + float(loss) * k, n + k
    model.train()
    return tot / max(n, 1)


@torch.no_grad()
def sample(model, tok, path, n=4, seed=0):
    model.eval()
    rows = [json.loads(l)["messages"] for l in Path(path).read_text().splitlines() if l.strip()]
    random.Random(seed).shuffle(rows)
    for ms in rows[:n]:
        i = max(k for k, m in enumerate(ms) if m["role"] == "user")
        enc = tok.apply_chat_template(ms[:i + 1], tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt")
        with torch.autocast("cuda", dtype=torch.float16):
            out = model.generate(input_ids=enc["input_ids"].cuda(), max_new_tokens=100, do_sample=False)
        print("  CHILD/EVENT:", ms[i]["content"].split("\n")[-2 if ms[i]["content"].endswith("Reply.") else -1][:110])
        print("  MODEL      :", tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=True).strip().replace("\n", " | ")[:260])
        print("  WRITTEN    :", ms[i + 1]["content"].replace("\n", " | ")[:260], flush=True)
    model.train()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="google/gemma-4-E2B-it")
    ap.add_argument("--data", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--out", default="adapter")
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--eval-every", type=float, default=0.5, help="epochs between held-out checks; the best adapter is the one saved")
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=3072)
    ap.add_argument("--init", default="", help="an earlier adapter dir to continue from (same rank and modules)")
    ap.add_argument("--dry", action="store_true", help="load, list the LoRA modules, encode the data, one step, then stop")
    a = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model

    tok = AutoTokenizer.from_pretrained(a.base)
    train, val = load(a.data, tok, a.max_len), load(a.val, tok, a.max_len)
    model = AutoModelForCausalLM.from_pretrained(
        a.base, device_map={"": 0}, dtype=torch.float16,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                               bnb_4bit_compute_dtype=torch.float16))
    print(type(model).__name__, f"GPU {torch.cuda.memory_allocated() / 2**30:.1f} GB after load", flush=True)
    # not peft's prepare_model_for_kbit_training: it casts every unquantized weight to float32, and E2B's per-layer embedding
    # table alone is then 9.4 GB (out of memory on a T4). Freezing + checkpointing is all that is needed here.
    for p in model.parameters():
        p.requires_grad_(False)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=a.rank, lora_dropout=0.05, bias="none",
                                             target_modules=TARGETS, task_type="CAUSAL_LM"))
    if a.init:      # continue an earlier round: its saved names are the checkpoint's (model.language_model.layers...), see the end of main
        from safetensors.torch import load_file
        own = dict(model.named_parameters())
        got = 0
        for k, v in load_file(str(Path(a.init) / "adapter_model.safetensors")).items():
            tail = k.split("layers.", 1)[1].replace(".lora_A.weight", ".lora_A.default.weight").replace(".lora_B.weight", ".lora_B.default.weight")
            hits = [n for n in own if n.endswith("layers." + tail) and "audio" not in n and "vision" not in n]
            assert len(hits) == 1, (k, hits[:3])
            own[hits[0]].data.copy_(v.to(own[hits[0]].dtype))
            got += 1
        print(f"continued from {a.init}: {got} tensors loaded", flush=True)
    names = [n for n, _ in model.named_modules() if n.endswith("lora_A")]
    print(len(names), "LoRA modules, e.g.", names[0], "...", names[-1])
    assert not any("audio" in n or "vision" in n for n in names)
    assert not any(re.search(rf"layers\.(\d+)\.self_attn\.[kv]_proj", n) and int(re.search(r"layers\.(\d+)\.", n).group(1)) >= SHARED_KV_FROM
                   for n in names)
    model.print_trainable_parameters()
    tc = getattr(model.config, "text_config", model.config)
    print("final_logit_softcapping:", getattr(tc, "final_logit_softcapping", None), flush=True)

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    steps = math.ceil(len(train) * a.epochs / a.accum)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / max(1, steps * 0.06)) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / steps))))
    scaler = torch.amp.GradScaler("cuda")
    print(f"val loss before: {val_loss(model, val):.3f}", flush=True)
    sample(model, tok, a.val)
    model.train()
    rng, seen, step, t0, run = random.Random(0), 0, 0, time.time(), []
    every, best = max(1, int(len(train) * a.eval_every)), float("inf")

    def check(tag):
        nonlocal best
        v = val_loss(model, val)
        keep = v < best
        if keep:
            best = v
            model.save_pretrained(a.out)
        print(f"== {tag} val loss {v:.3f}{'  (best so far, saved)' if keep else '  (worse: not saved)'}", flush=True)
    total = int(len(train) * a.epochs)
    while seen < total:
        order = list(range(len(train)))
        rng.shuffle(order)
        for j in order:
            if seen >= total:
                break
            x, y = train[j]
            loss = lm_loss(model, x, y)
            if not torch.isfinite(loss):
                print("non-finite loss, example skipped", flush=True)
                opt.zero_grad(set_to_none=True)
                continue
            scaler.scale(loss / a.accum).backward()
            run.append(float(loss.detach()))
            seen += 1
            if seen % a.accum == 0 or seen == total:
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                scaler.step(opt); scaler.update(); opt.zero_grad(set_to_none=True); sched.step()
                step += 1
                if step % 5 == 0 or a.dry:
                    print(f"step {step}/{steps} epoch {seen / len(train):.2f} loss {sum(run) / len(run):.3f} "
                          f"{(time.time() - t0) / seen:.2f} s/example GPU {torch.cuda.max_memory_allocated() / 2**30:.1f} GB", flush=True)
                    run = []
                if a.dry:
                    return
            if seen % every == 0 and seen < total:
                check(f"epoch {seen / len(train):.2f}")
    check("end")
    print(f"best val loss {best:.3f}  ({(time.time() - t0) / 60:.1f} min)", flush=True)
    sample(model, tok, a.val)
    # llama.cpp's converter expects the checkpoint's tensor names (model.language_model.layers.N...)
    from safetensors.torch import load_file, save_file
    f = Path(a.out) / "adapter_model.safetensors"
    sd = load_file(str(f))
    fixed = {}
    for k, v in sd.items():
        k2 = k if "language_model" in k else re.sub(r"^(base_model\.model\.)(?:model\.)?layers\.", r"\1model.language_model.layers.", k)
        fixed[k2] = v.float()
    save_file(fixed, str(f))
    print("saved", a.out, len(fixed), "tensors, e.g.", next(iter(fixed)))


if __name__ == "__main__":
    main()
