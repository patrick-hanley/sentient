import sys, os, time, wave, numpy as np
which = sys.argv[1]
os.sched_setaffinity(0, {3})
LINES = ["Seven times eight is fifty-six!", "Seven times eight is fifty-six! That is like seven rows of eight penguins.", "Hmm, that is a great question. Let us think about how plants grow, shall we?"]
def report(name, fn, sr_of):
    fn("Warm up.")
    for i, L in enumerate(LINES):
        t = time.time(); a = np.asarray(fn(L)).squeeze(); dt = time.time() - t
        sec = len(a) / sr_of
        print(f"{name:28} line{i}: {sec:4.1f}s speech in {dt:5.2f}s  x{sec/dt:5.1f} realtime", flush=True)
        if i == 1:
            x = (np.clip(a.astype(np.float32), -1, 1) * 32767).astype("<i2")
            with wave.open(f"/data/bench-out/{name}.wav", "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(sr_of)); w.writeframes(x.tobytes())
if which == "kokoro":
    import onnxruntime as rt
    from kokoro_onnx import Kokoro
    o = rt.SessionOptions(); o.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL
    k = Kokoro.from_session(rt.InferenceSession("/data/sentient/offline/kokoro/kokoro-v1.0.int8.onnx", sess_options=o, providers=["CPUExecutionProvider"]), "/data/sentient/offline/kokoro/voices-v1.0.bin")
    for v in ("af_heart", "am_eric"):
        report("kokoro_int8_" + v, lambda L, v=v: k.create(L, voice=v, lang="en-us")[0], 24000)
elif which == "supertonic":
    from supertonic import TTS
    tts = TTS(auto_download=True)
    for v in ("M1", "F1"):
        st = tts.get_voice_style(voice_name=v)
        def f(L, st=st):
            wav, dur = tts.synthesize(L, voice_style=st, lang="en"); return wav
        report("supertonic3_" + v, f, tts.sample_rate)
elif which == "kitten":
    from kittentts import KittenTTS
    for mdl in ("kitten-tts-nano-0.8-int8", "kitten-tts-nano-0.8-fp32"):
        m = KittenTTS("KittenML/" + mdl)
        for v in ("Jasper", "Bella"):
            report(f"{mdl[10:]}_{v}", lambda L, v=v: m.generate(L, voice=v), 24000)
