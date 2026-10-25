#!/usr/bin/env python3
"""Reproducible scheduling benchmark with simulated stages, not hardware/model speed.

python tools/benchmark_latency.py --runs 5 --output benchmark.json
Requires NumPy and webrtcvad-wheels; no models, network, cameras or audio devices.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics
import sys
import threading
import time
import types

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from brain import config
from brain.director import Director, parse


class Model:
    hears_audio=True
    def stream(self,*args,**kwargs):
        time.sleep(.08)
        yield "HEARD: -\nDYNO: Hello, friend!\n"
        time.sleep(.42)
        yield "SAGE: Shall we play?"
    def ask(self,*args,**kwargs):
        return "".join(self.stream(*args,**kwargs))


class Voices:
    def render(self,*args):
        time.sleep(.08)
        return b"\0\0"*320


class Hub:
    def __init__(self):
        self.first_post=None
        self.response_active=threading.Event()
    def online(self):return ["dyno","sage"]
    def play(self,toy,pcm,*,on_dispatch=None,raise_on_error=False):
        if self.first_post is None:self.first_post=time.monotonic()
        if on_dispatch:on_dispatch()
        time.sleep(.20)


def run(streaming):
    model,voices,hub=Model(),Voices(),Hub()
    started=time.monotonic()
    if streaming:
        eyes=types.SimpleNamespace(views={},scene_text=lambda:"DYNO sees the child.")
        director=Director(hub,voices,eyes,model,{})
        director._turn(event="The child waved.")
        if director.last_trace["status"]!="ok":raise RuntimeError(director.last_trace)
    else:
        output=model.ask("The child waved.")
        _,lines=parse(output,"dyno",hub.online())
        for toy,text in lines:hub.play(toy,voices.render(toy,text))
    return {"first_audio_post_ms":(hub.first_post-started)*1000,
            "turn_total_ms":(time.monotonic()-started)*1000}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs",type=int,default=5)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if not 1<=args.runs<=100:parser.error("--runs must be 1–100")
    config.apply_latency_profile("responsive")
    samples={"serial":[],"pipelined":[]}
    for _ in range(args.runs):
        samples["serial"].append(run(False));samples["pipelined"].append(run(True))
    medians={key:{metric:round(statistics.median(row[metric] for row in values),2)
                  for metric in values[0]} for key,values in samples.items()}
    result={"kind":"simulated_stage_scheduling_only","board_benchmark":False,
            "acoustic_onset_measured":False,"runs":args.runs,
            "simulated_stage_ms":{"model_first_line":80,"model_remaining":420,"tts_per_line":80,"playback_per_line":200},
            "median_ms":medians,"samples_ms":samples,
            "first_audio_post_reduction_percent":round(100*(1-medians["pipelined"]["first_audio_post_ms"]/medians["serial"]["first_audio_post_ms"]),1),
            "configured_waits_ms":{"previous_endpoint":700,"previous_max_arbitration":350,
                                   "responsive_endpoint":500,"responsive_max_arbitration":120}}
    output=json.dumps(result,indent=2)+"\n"
    if args.output:args.output.write_text(output)
    print(output,end="")


if __name__=="__main__":main()
