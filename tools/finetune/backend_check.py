"""The brain's own llama.cpp backend with audio in (SENTIENT_LLAMA_AUDIO=1): hears a clip, survives an early stop, answers next.
Run on the Jetson with the brain stopped:
  SENTIENT_LLAMA_AUDIO=1 SENTIENT_LLAMA_SERVER=/data/build/llama.cpp/build/bin/llama-server .venv-brain/bin/python tools/finetune/backend_check.py"""
import sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain import llm  # noqa: E402
from brain.director import system_prompt  # noqa: E402
from step0_runtime import TURN, clips, score  # noqa: E402

b = llm.make_backend("llamacpp", system_prompt(), gpu=True)
print("backend:", b.name, b.device, "hears audio:", b.hears_audio)
try:
    with tempfile.TemporaryDirectory(dir="/dev/shm") as d:
        cs = clips(d)[:4]
        b.ask(TURN, wav=cs[0][1]); b.reset_conversation()
        for said, wav in cs:
            t = time.time()
            out = b.ask(TURN + "The child just spoke (audio attached). Reply.", wav=wav)
            print(f"  {score(said, out)[1]*100:3.0f}%  {time.time()-t:.2f}s  {out[:110]!r}")
        for i in range(3):
            s = b.stream("[SCENE] Nothing.\n[EVENT] Tell a long story about a dragon. Write four lines, DYNO: and PENNY: alternating.")
            first = next(s); s.close()                     # stop early, as a forced look does
            t = time.time()
            out = b.ask("[EVENT] PENNY says hi in one short line.")
            print(f"  cut after {first[:12]!r} -> next reply {out[:50]!r} {time.time()-t:.2f}s")
    print("PASS")
finally:
    if b.server:
        b.server.terminate()
