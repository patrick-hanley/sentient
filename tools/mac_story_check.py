"""Live story check judged by the Mac mic (the reference for "did it work"): the Mac reads the story aloud with `say`, pauses after
each sentence, and reports what was audible in each pause.  python tools/mac_story_check.py out.json   (brain running, toys near the Mac)"""
import subprocess, sys, time, json, numpy as np
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__))); import mac_ear as ear
PLAN = [("I'm going to read you a story.", 7, "ack"),
 ("A man had a donkey who had carried sacks to the mill for many years.", 5, ["donkey"]),
 ("On the road he found a hound, lying and panting.", 5, ["dog"]),
 ("Then they came to a cat, sitting on the path, with a face like three rainy days.", 5, ["cat"]),
 ("A rooster sat on the gate, crowing with all his might.", 6, ["rooster"]),
 ("They saw a light far away and walked toward it.", 4, []),
 ("Inside the house, robbers were sitting at a table full of good food.", 4, []),
 ("The donkey brayed, the hound barked, the cat mewed, and the rooster crowed.", 10, ["donkey", "dog", "cat", "rooster"]),
 ("Then they burst through the window, so that the glass clattered.", 5, ["glass"]),
 ("And the four musicians lived happily in the house.", 4, []),
 ("The end.", 12, "end")]
if "--short" in sys.argv:      # start, one sentence, the end
    sys.argv.remove("--short"); PLAN = [PLAN[0], PLAN[3], PLAN[-1]]
STORY = ["donkey", "dog", "cat", "rooster", "glass"]
E = ear.Ear(); time.sleep(1.5); marks = []
print("start", time.strftime("%H:%M:%S"), flush=True)
for text, wait, exp in PLAN:
    subprocess.run(["say", "-r", "165", text], check=True); a = E.now(); time.sleep(wait); marks.append((text, exp, a, E.now()))
x = E.stop(); e = np.sqrt((x[:len(x)//800*800].astype(np.float32).reshape(-1, 800) ** 2).mean(1)); floor = float(np.median(e[e < np.percentile(e, 40)]))
print("room floor", round(floor)); res = []
for text, exp, a, b in marks:
    seg = x[int(a * 16000):int(b * 16000)]; bs = ear.bursts(seg, floor, mult=4.0, min_s=0.1, join_s=0.2)
    line = {"said": text[:34], "expect": exp, "heard": [(s, round(e_ - s, 2), r) for s, e_, r in bs]}
    if isinstance(exp, list) and bs:
        ids = []
        for s, e_, r in bs:
            m = [(sc, n) for sc, n in ear.match(seg[int(max(0, s - .1) * 16000):int((e_ + .1) * 16000)]) if n in STORY]
            ids.append(f"{m[0][1]}({m[0][0]})")
        line["sounds_like"] = ids
    res.append(line); print(line, flush=True)
json.dump(res, open(sys.argv[1], "w"))
