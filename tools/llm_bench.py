"""Time Gemma through the brain's own backends: first token, first complete line, total. Usage: llm_bench.py litert-cpu|litert-gpu|llamacpp"""
import sys, time, statistics, os
sys.path.insert(0, "/data/sentient")
from brain import config
from brain.director import system_prompt
from brain import llm

kind = sys.argv[1]
if kind.startswith("litert"):
    be = llm.LiteRTBackend(system_prompt(), gpu=kind.endswith("gpu"))
    print("device:", be.device)
else:
    be = llm.LlamaCppBackend(system_prompt())
PROMPTS = [
 "[TOYS HERE] DYNO, SAGE, PENNY (only these toys may speak) | [SCENE] DYNO sees nothing in particular. SAGE sees nothing. PENNY sees nothing. | [EVENT] The child said: why is the sky blue?",
 "[TOYS HERE] DYNO, SAGE, PENNY (only these toys may speak) | [SCENE] nothing | [EVENT] Nobody has talked for a while. The toys chat about a tricky spelling word. [ORDER] DYNO, SAGE, PENNY. One short line each.",
 "[TOYS HERE] DYNO, SAGE, PENNY (only these toys may speak) | [SCENE] nothing | [EVENT] The child said: can you tell me a joke about penguins?",
 "[TOYS HERE] DYNO, SAGE, PENNY (only these toys may speak) | [SCENE] nothing | [EVENT] The child said: what is seven times eight?",
 "[TOYS HERE] DYNO, SAGE, PENNY (only these toys may speak) | [SCENE] nothing | [EVENT] The child said: I am sad today.",
]
if hasattr(be, "warm"): be.warm()
rows = []
for i, p in enumerate(PROMPTS * 2):
    if hasattr(be, "reset_conversation") and i % 3 == 0 and kind == "llamacpp": be.history = []
    t0 = time.time(); first = line = None; buf = ""
    for ch in be.stream(p):
        if first is None: first = time.time() - t0
        buf += ch
        if line is None and "\n" in buf.strip("\n") : line = time.time() - t0
    tot = time.time() - t0
    rows.append((first, line or tot, tot, len(buf)))
    print(f"{i}: first token {first:.2f}s  first line {line or tot:.2f}s  total {tot:.2f}s  {len(buf)} chars", flush=True)
r = rows[1:]
print("MEDIAN first token %.2f  first line %.2f  total %.2f" % tuple(statistics.median(x[k] for x in r) for k in range(3)))
