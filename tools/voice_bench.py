import sys,time,statistics
sys.path.insert(0,"/data/sentient")
from brain.tts import Voices
v=Voices()
L=["Seven times eight is fifty-six!","Seven times eight is fifty-six! That is like seven rows of eight penguins.","That is a great question. Let us think about how plants grow, shall we?"]
for toy in ("dyno","sage","penny"):
    v.render(toy,"Warm up.")
    for i,t in enumerate(L):
        t0=time.time();b=v.render(toy,t);dt=time.time()-t0;sec=len(b)/2/16000
        print(f"{toy} line{i}: {sec:4.1f}s speech in {dt:4.2f}s x{sec/dt:4.1f}",flush=True)
