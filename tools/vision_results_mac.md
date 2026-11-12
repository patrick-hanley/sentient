Device: patricks-MacBook-Pro.local x86_64 CPU. Prompt: "Name the main object in one short sentence a child would understand.". Latency excludes a warm-up call.

| Model | Params | Hit rate | Median s | p90 s | Peak RSS MB |
|---|---|---|---|---|---|
| SmolVLM-256M Q8 | 0.26B | 32/36 (89%) | 2.79 | 3.02 | 578 |
| SmolVLM-500M Q8 | 0.5B | 30/36 (83%) | 3.26 | 3.56 | 1002 |
| Florence-2-base (fp32) | 0.23B | 32/36 (89%) | 4.15 | 4.35 | 1766 |
| Moondream2 (fp32) | 1.9B | 35/36 (97%) | 24.74 | 49.41 | 7863 |
| Gemma 4 E2B Q4_0 (+mmproj Q8) | 5.1B (2.3B eff.) | 30/36 (83%) | 3.25 | 3.63 | 4564 |
| Qwen3-VL-2B Q8 | 2.1B | 35/36 (97%) | 8.90 | 9.79 | 3551 |
