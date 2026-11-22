# Fine-tuning the toys' Gemma (pilot)

Plan and results: `gemma-kids-social-model-plan.md` in the repo root. Everything here uses synthetic scenes only; a real
child's words never go into these files or to a rented GPU.

| File | What it does |
|---|---|
| `WRITING.md` | The brief for writing scenes (the toys' rules, the file format). |
| `scenes.py check` | Checks every scene against the toys' rules (who answers, line limits, stop, feelings, facts, sounds). |
| `scenes.py render` | Turns checked scenes into training examples in the brain's real prompt format (`train.jsonl`, `train-val.jsonl`). |
| `data/pilot-[a-d].jsonl`, `round2-[e-l].jsonl`, `round3-[m-p].jsonl` | 1,200 scenes written by Claude, all passing the checker. Round 3 adds camera, I spy and always-answer turns. |
| `data/round4-q.jsonl` | 50 attachment-style scenes (anxious, avoidant, push-pull, exclusivity, secure) for the reply rubric's feelings and attachment-risk rows. |
| `make_train4.py` | Builds the round 4 mix: `data/train4.jsonl` (44 new + 66 round-3 + 66 earlier scenes) and `train4-val.jsonl` (the 64 held-out scenes of round 3 + 6 new, listed in `round4-heldout.jsonl`). Same output every run. |
| `data/train3.jsonl`, `train3-val.jsonl` | Round 3 training mix (176 new + 320 earlier scenes) and held-out set (40 earlier + 24 new), half with a brain-shaped spoken history. |
| `train_lora.py` | LoRA training on one 16 GB GPU (Colab T4): language layers only, loss on the toys' replies only. |
| `eval_rules.py` | Scores a model on held-out scenes with the same checker, on the Jetson through llama.cpp. |
| `step0_runtime.py` | Hearing and speed check: the same spoken clips through LiteRT-LM and llama.cpp (optionally with an adapter). |
| `backend_check.py` | The brain's own llama.cpp backend with audio in: hears, survives an early stop. |
| `merge_lora.py` | Merges an adapter into the original weights, tensor by tensor (runs on the Jetson). |
| `make_random_lora.py` | An untrained adapter, used once to prove the adapter -> GGUF -> llama.cpp path. |

## One training round

1. Write or extend scenes, then `python tools/finetune/scenes.py check tools/finetune/data/*.jsonl` until 0 fail.
2. `python tools/finetune/scenes.py render tools/finetune/data/pilot-*.jsonl -o tools/finetune/data/train.jsonl`
3. In Colab (T4 GPU): upload `train_lora.py`, `train.jsonl`, `train-val.jsonl`; `pip install bitsandbytes`;
   `python train_lora.py --data train.jsonl --val train-val.jsonl --out adapter` (about 35 minutes for 180 scenes, 3 epochs).
   Download `adapter/` (two files).
4. On the Jetson (brain stopped; needs `/data/ft/gemma-4-E2B-it/model.safetensors`, 10 GB, and about 16 GB of temporary swap for
   the convert step), merge the adapter into the weights and quantize the result. Do not load the adapter at runtime:
   `/data/ft/venv/bin/python tools/finetune/merge_lora.py /data/ft/gemma-4-E2B-it <adapter dir> /data/ft/merged-<name>`
   `/data/ft/venv/bin/python /data/build/llama.cpp/convert_hf_to_gguf.py /data/ft/merged-<name> --use-temp-file --outtype f16 --outfile /data/ft/merged-<name>-f16.gguf`
   `/data/build/llama.cpp/build/bin/llama-quantize /data/ft/merged-<name>-f16.gguf /data/ft/toys-<name>-Q4_0.gguf Q4_0`
5. Score tuned and untuned on the same held-out scenes:
   `python tools/finetune/eval_rules.py tools/finetune/data/train2-val.jsonl tools/finetune/data/*-?.jsonl --limit 40 [--gguf /data/ft/toys-<name>-Q4_0.gguf]`
   and the hearing check: `STEP0_GGUF=/data/ft/toys-<name>-Q4_0.gguf python tools/finetune/step0_runtime.py llama`.
6. To try it in the brain:
   `SENTIENT_GGUF=/data/ft/toys-<name>-Q4_0.gguf SENTIENT_LLAMA_AUDIO=1 SENTIENT_LLAMA_SERVER=/data/build/llama.cpp/build/bin/llama-server python -m brain.main --backend llamacpp`.

## Things that bit us

- The `.litertlm` file cannot take a LoRA; the tuned model runs on llama.cpp (GGUF + the mmproj with the audio encoder).
- E2B's layers 15-34 share the key/value cache: no `k_proj` / `v_proj` LoRA there, or llama.cpp refuses the adapter.
- On a T4, `peft.prepare_model_for_kbit_training` runs out of memory (it casts the 9 GB embedding table to float32), and
  so does the stock loss (logits over a 262k vocabulary for every token). `train_lora.py` avoids both.
- Colab's Files panel does not overwrite an uploaded file of the same name: delete the old one first.
- An adapter loaded at runtime onto the 4-bit GGUF misbehaves (it was trained against the unrounded weights): round 2 scored 48%
  that way and 82% merged-then-quantized. Always merge first.
- Colab's free GPU quota ran out after about 3.5 hours in one day, and the merge needs more than its 12 GB of RAM. The merge,
  convert and quantize steps all run on the Jetson instead.
- Leaving a kind of turn out of the scenes un-teaches it: rounds 1-2 had no camera turns and the tuned model stopped answering
  LOOK; the stop scenes (reply: nothing) spread to silence after plain remarks. Every protocol the brain relies on needs scenes.
- Round 3 continues from the round-2 adapter: `python train_lora.py --data train3.jsonl --val train3-val.jsonl --init adapter-round2
  --out adapter --epochs 2` (upload the round-2 adapter folder as `adapter-round2`).

- Round 4 continues from the round-3 adapter the same way: `python tools/finetune/make_train4.py`, then in Colab
  `python train_lora.py --data train4.jsonl --val train4-val.jsonl --init adapter-round3 --out adapter --epochs 2`. Five earlier
  scenes are left out of the replay because a toy line in them does what round 4 teaches against ("I'll miss you too").