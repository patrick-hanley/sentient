"""Does the model follow the toys' rules on scenes it never trained on? (gemma-kids-social-model-plan.md, section 6)

For every turn of the held-out scenes, the model gets the brain's real system prompt and the conversation so far (the written
replies as history) and writes its own reply. The reply is then judged by the same rule checker the training scenes had to
pass (tools/finetune/scenes.py: who may answer, line and word limits, stop means stop, feelings, facts, noises, sounds).
Run once per model on the Jetson with the brain stopped, then compare the two tables:

  python tools/finetune/eval_rules.py tools/finetune/data/train-val.jsonl tools/finetune/data/pilot-*.jsonl [--lora adapter.gguf]
      [--gguf model.gguf] [--out result.json]
Numbers only in the output file; the generated lines are printed for a sample (--show N), never saved.
"""
from __future__ import annotations

import argparse, collections, json, re, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain import config  # noqa: E402
from brain.director import LINE, NAMES  # noqa: E402
import scenes  # noqa: E402

LLAMA = config.LLAMA_SERVER or "/data/build/llama.cpp/build/bin/llama-server"
PORT = 8092
BY_NAME = {v.upper(): k for k, v in NAMES.items()}


def parse(reply: str):
    heard, lines = None, []
    for raw in reply.splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        who, text = m.group(1).upper(), m.group(2).strip()
        if who == "HEARD":
            heard = text
        elif text:
            lines.append([BY_NAME[who], text])
    return heard, lines


def ask(msgs, seed):
    body = {"messages": msgs, "max_tokens": 120, "temperature": 0.8, "seed": seed, "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"] or "", time.time() - t


def rule(problem: str) -> str:
    p = problem.split(": ", 1)[1] if problem.startswith("turn ") else problem
    p = re.sub(r"^(dyno|sage|penny): ", "", p)
    if p.startswith("attachment: "):
        return p
    for key, name in (("only", "named toy: others answered"), ("answers first", "wrong toy answered first"), ("words (max", "line too long"),
                      ("two sentences", "more than two sentences"), ("said stop", "talked after stop"), ("grown-up", "feeling: no grown-up"),
                      ("wrong fact", "wrong fact"), ("spelled noise", "spelled noise"), ("sound", "bad sound tag"), ("twice in a row", "same toy twice"),
                      ("child leads", "more than two toys on a child turn"), ("1-4 toy lines", "no toy line / too many"),
                      ("personal", "asks personal info"), ("emoji", "emoji or action"), ("vocalization", "unknown [bracket]"),
                      ("not in this scene", "absent toy spoke"), ("referee", "I spy: guessed a thing not in the list"),
                      ("nothing seen", "I spy: guessed with nothing seen"), ("camera failed", "camera failed: wrong toy / lines"),
                      ("I spy: only", "I spy: wrong toy / lines")):
        if key in p:
            return name
    return p[:40]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("val")
    ap.add_argument("scene_files", nargs="+")
    ap.add_argument("--gguf", default=str(config.MODEL_GGUF))
    ap.add_argument("--lora", default="")
    ap.add_argument("--scale", type=float, default=1.0, help="adapter strength (1 = as trained)")
    ap.add_argument("--out", default="")
    ap.add_argument("--show", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--samples", type=int, default=3, help="replies drawn per turn (different seeds)")
    ap.add_argument("--live-history", action="store_true", help="earlier child turns as the brain's history holds a spoken turn (no words in the user text)")
    a = ap.parse_args()
    ids = [json.loads(l)["id"] for l in Path(a.val).read_text().splitlines() if l.strip()]
    by_id = {sc["id"]: sc for _, _, sc in scenes.load(a.scene_files)}
    todo = [by_id[i] for i in ids][:a.limit or None]
    snd = scenes.sounds()
    cmd = [LLAMA, "-m", a.gguf, "--port", str(PORT), "-c", "8192", "-ngl", "99", "-np", "1", "--reasoning-budget", "0"]
    if a.lora:
        cmd += ["--lora", a.lora] if a.scale == 1.0 else ["--lora-scaled", f"{a.lora}:{a.scale}"]
    log = open("/tmp/eval-llama.log", "w")
    srv = subprocess.Popen(cmd, stdout=log, stderr=log)
    try:
        for _ in range(180):
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("llama-server did not come up; see /tmp/eval-llama.log")
        counts, n_turns, clean, words, nlines, questions, secs, heard_ok, shown = collections.Counter(), 0, 0, [], [], 0, [], 0, 0
        kinds = collections.defaultdict(lambda: [0, 0])      # turn kind -> [clean, replies]
        for sc in todo:
            toys = sc.get("toys") or scenes.TOYS
            msgs = [{"role": "system", "content": scenes.system_for(sc)}]
            for k, t in enumerate(sc["turns"]):
                prev = sc["turns"][k - 1] if k else None
                kind = "look" if t.get("look") else "stop" if t["type"] == "child" and not t["reply"] else t["type"]
                msgs.append({"role": "user", "content": scenes.user_text(t, toys, sc, prev)})
                for smp in range(a.samples):
                    reply, dt = ask(msgs, seed=k + 1000 * smp)
                    heard, lines = parse(reply)
                    asked = bool(re.search(r"(?m)^\s*LOOK\s*$", reply))
                    if kind == "look":
                        bad = [] if asked and not lines else ["look request: no LOOK"]
                    else:
                        probe = {"id": "x", "scenario": "x", "toys": toys, "cameras": sc.get("cameras", "request"),
                                 "turns": [prev or dict(t, reply=lines), dict(t, reply=lines)]}
                        bad = sorted({rule(b) for b in scenes.check_scene(probe, snd) if b.startswith("turn 1")})
                        if kind == "stop" and not lines:
                            bad = []                                  # stop: silence is right
                        if asked:
                            bad.append("LOOK when not asked")
                    kinds[kind][0] += not bad
                    kinds[kind][1] += 1
                    want = scenes.heard_text(t, prev)
                    heard_ok += (heard or "").strip().lower().rstrip(".!?") == want.lower().rstrip(".!?")
                    n_turns += 1
                    clean += not bad
                    counts.update(bad)
                    secs.append(dt)
                    nlines.append(len(lines))
                    for _, x in lines:
                        words.append(len(scenes.TAG.sub(" ", x).split()))
                        questions += x.rstrip().endswith("?")
                    if shown < a.show and (bad or k == 0):
                        shown += 1
                        print(f"[{sc['id']} turn {k}] {('CHILD: ' + t['said']) if t['type'] == 'child' else 'EVENT'}\n   MODEL: {reply.strip()[:300]!r}\n   RULES: {bad or 'clean'}")
                if a.live_history and t["type"] in ("child", "ispy"):
                    msgs[-1] = {"role": "user", "content": scenes.user_text(t, toys, sc, prev, audio=True)}
                msgs.append({"role": "assistant", "content": scenes.target_text(t, prev)})     # the written reply is the history
        res = {"model": Path(a.gguf).name + (f" + {Path(a.lora).name} x{a.scale}" if a.lora else ""), "scenes": len(todo), "replies": n_turns, "samples_per_turn": a.samples,
               "clean_turns_pct": round(100 * clean / n_turns, 1), "heard_exact_pct": round(100 * heard_ok / n_turns, 1),
               "lines_per_turn": round(sum(nlines) / n_turns, 2), "words_per_line": round(sum(words) / max(1, len(words)), 1),
               "question_lines_pct": round(100 * questions / max(1, len(words)), 1),
               "median_reply_s": round(sorted(secs)[len(secs) // 2], 2), "live_history": a.live_history,
               "clean_pct_by_turn_kind": {k: [round(100 * c / n, 1), n] for k, (c, n) in sorted(kinds.items())},
               "violations": dict(counts.most_common())}
        print(json.dumps(res, indent=1))
        if a.out:
            Path(a.out).write_text(json.dumps(res, indent=1))
    finally:
        srv.terminate()
        srv.wait(10)


if __name__ == "__main__":
    main()
