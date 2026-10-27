import os,time,numpy as np
os.sched_setaffinity(0,{3})
from supertonic import TTS
tts=TTS(auto_download=True); st=tts.get_voice_style(voice_name="M1")
L="Seven times eight is fifty-six! That is like seven rows of eight penguins."
tts.synthesize("Warm up.",voice_style=st,lang="en")
for n in (2,3,4,5,8):
    r=[]
    for _ in range(2):
        t=time.time(); wav,dur=tts.synthesize(L,voice_style=st,lang="en",total_steps=n,silence_duration=0.0); r.append(time.time()-t)
    sec=len(np.asarray(wav).squeeze())/tts.sample_rate
    print(f"supertonic steps={n}: {sec:.1f}s speech in {min(r):.2f}s x{sec/min(r):.1f}")
